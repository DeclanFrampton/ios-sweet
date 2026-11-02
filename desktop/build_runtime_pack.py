"""Maintainer-only: publish dependencies for the clone-and-run source launcher.

Unlike build.py this produces NO application installer or frozen app. Studio's
code still runs from the user's checkout. Only Python + vendored dependencies,
native QEMU, the local signer and source-built open-source guest helpers ship.
Apple SDK/firmware, IPAs, raw disks, guest credentials and device data never do.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PYTHON_VERSION='3.14.10'
PYTHON_SHA256='90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159'
PYTHON_URL=f'https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip'
HELPERS=('prepare-kernel','prepare-initrd.gz','iossweet-agent','iossweet-net-seed','kernel.aks-quiet.sweet')
QEMU_FILES=('qemu-system-aarch64.exe','qemu-system-x86_64.exe','qemu-img.exe','COPYING','COPYING.LIB','README.rst')
BIOS=('bios-256k.bin','bios.bin','bios-microvm.bin','kvmvapic.bin','vgabios-stdvga.bin',
      'vgabios-virtio.bin','efi-e1000e.rom','efi-e1000.rom','pxe-e1000.rom','pxe-e1000e.rom')
SIGNER_SHA256='fd5aeb908f1d3be60f7e372003772f52a6ce4148106d3aaf22aec6861f5d8a5e'


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
    return h.hexdigest()


def unpack(archive,destination,wheel=False):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            name=entry.filename
            if '\\' in name or ':' in name or name.startswith('/') or '..' in name.split('/'):
                raise ValueError('Unsafe dependency archive path')
            if stat.S_IFMT(entry.external_attr>>16)==stat.S_IFLNK:
                raise ValueError('Dependency archive contains symlinks')
            parts=PurePosixPath(name).parts
            if wheel and parts[0].endswith('.data'):
                if len(parts)<3 or parts[1] not in ('purelib','platlib'):
                    # Console scripts/headers aren't needed for the application.
                    continue
                parts=parts[2:]
            target=destination.joinpath(*parts)
            if not target.resolve().is_relative_to(destination.resolve()):raise ValueError('Dependency path escape')
            if entry.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():raise ValueError('Dependency file collision: '+str(target.relative_to(destination)))
            with z.open(entry) as src,target.open('xb') as out:shutil.copyfileobj(src,out,1024**2)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--python-zip',required=True,type=Path)
    p.add_argument('--wheels',required=True,type=Path)
    p.add_argument('--assets',required=True,type=Path)
    p.add_argument('--qemu',required=True,type=Path)
    p.add_argument('--signer-zip',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--version',default='studio-runtime-v0.2.0-r1')
    a=p.parse_args()
    import re
    if not re.fullmatch(r'studio-runtime-v[0-9A-Za-z._-]+',a.version):p.error('Invalid immutable release tag')
    if digest(a.python_zip)!=PYTHON_SHA256:raise ValueError('Official Python archive checksum mismatch')
    if digest(a.signer_zip)!=SIGNER_SHA256:raise ValueError('Official rcodesign archive checksum mismatch')
    output=a.output.resolve();output.mkdir(parents=True,exist_ok=True)
    staging=output/'runtime'
    if staging.exists():raise ValueError('Choose a new output directory; old packs will not be overwritten')
    staging.mkdir()
    python=staging/'python';unpack(a.python_zip,python)
    # Deliberate app-local vendor directory; no pip, global Python installation,
    # registry Python path, or user site-packages are used on client machines.
    (python/'python314._pth').write_text('python314.zip\n.\nsite-packages\nimport site\n',encoding='ascii')
    requirements={}
    for line in (ROOT/'desktop/runtime-requirements.txt').read_text().splitlines():
        if line and not line.startswith('#'):
            name,version=line.split('==');requirements[name.replace('-','_').lower()]=version
    wheels=list(a.wheels.glob('*.whl'));found=set();provenance=[]
    for path in sorted(wheels):
        name,version,*tags=path.name.split('-');canonical=name.lower().replace('-','_')
        if requirements.get(canonical)!=version:raise ValueError('Unexpected wheel/version: '+path.name)
        if canonical in found:raise ValueError('Duplicate wheel distribution: '+canonical)
        found.add(canonical)
        with urllib.request.urlopen(f'https://pypi.org/pypi/{canonical}/{version}/json',timeout=30) as r:metadata=json.load(r)
        expected=next((u for u in metadata['urls'] if u['filename']==path.name),None)
        actual=digest(path)
        if expected:
            if actual!=expected['digests']['sha256']:raise ValueError('PyPI checksum mismatch: '+path.name)
            origin={'url':expected['url'],'sha256':actual}
        elif canonical=='proxy_tools':
            source=next(u for u in metadata['urls'] if u['packagetype']=='sdist')
            origin={'builtFrom':source['url'],'sourceSha256':source['digests']['sha256'],'wheelSha256':actual}
        else:raise ValueError('Wheel not found in authoritative PyPI metadata: '+path.name)
        provenance.append({'name':canonical,'version':version,'filename':path.name,**origin})
        unpack(path,python/'site-packages',wheel=True)
    if found!=set(requirements):raise ValueError('Missing wheel dependencies: '+repr(set(requirements)-found))
    assets=staging/'assets';assets.mkdir()
    manifest=json.loads((a.assets/'manifest.json').read_text())
    for name in HELPERS:
        if digest(a.assets/name)!=manifest[name]:raise ValueError('Helper manifest mismatch: '+name)
        shutil.copy2(a.assets/name,assets/name)
    shutil.copy2(a.assets/'manifest.json',assets/'manifest.json')
    if (a.assets/'licenses').is_dir():shutil.copytree(a.assets/'licenses',assets/'licenses')
    # Include the upstream signer distribution, not a private signing profile.
    with zipfile.ZipFile(a.signer_zip) as z:
        exe=next(i for i in z.infolist() if PurePosixPath(i.filename).name=='rcodesign.exe')
        with z.open(exe) as src,(assets/'rcodesign.exe').open('xb') as out:shutil.copyfileobj(src,out)
        for entry in z.infolist():
            name=PurePosixPath(entry.filename).name
            if name.lower().startswith(('license','copying','readme')) and not entry.is_dir():
                dest=staging/'licenses'/'rcodesign'/name;dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes(z.read(entry))
    qemu=assets/'qemu';qemu.mkdir()
    for name in QEMU_FILES:
        if not (a.qemu/name).is_file():raise ValueError('QEMU runtime file missing: '+name)
        shutil.copy2(a.qemu/name,qemu/name)
    for lib in a.qemu.glob('*.dll'):shutil.copy2(lib,qemu/lib.name)
    (qemu/'share').mkdir()
    for name in BIOS:
        if (a.qemu/'share'/name).exists():shutil.copy2(a.qemu/'share'/name,qemu/'share'/name)
    for directory in ('licenses','license'):
        if (a.qemu/directory).is_dir():shutil.copytree(a.qemu/directory,qemu/directory)
    shutil.copy2(ROOT/'desktop/THIRD_PARTY_NOTICES.md',staging/'THIRD_PARTY_NOTICES.md')
    shutil.copy2(ROOT/'LICENSE',staging/'LICENSE')
    (staging/'PROVENANCE.json').write_text(json.dumps({'python':{'version':PYTHON_VERSION,'url':PYTHON_URL,'sha256':PYTHON_SHA256},
        'dependencies':provenance,'guestHelperHashes':manifest,'sourceRepository':'https://github.com/danhol86/ios-sweet'},indent=2))
    inventory={}
    for f in sorted(staging.rglob('*')):
        if not f.is_file():continue
        if f.suffix.lower() in ('.ipa','.raw','.qcow2','.dmg','.p8','.p12','.mobileprovision','.mobileconfig') or f.name in ('bridge.json','bridge.plist','device.json','host-bridge.json'):
            raise ValueError('Private artifact must never be published: '+f.name)
        inventory[f.relative_to(staging).as_posix()]=digest(f)
    inventory_path=staging/'runtime-manifest.json'
    inventory_path.write_text(json.dumps({'schema':1,'version':a.version,'files':inventory},indent=2))
    archive=output/(a.version+'-windows-x64.zip')
    print('Building public dependency ZIP ('+str(len(inventory))+' files; no application installer or Apple firmware)',flush=True)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in sorted(staging.rglob('*')):
            if f.is_file():z.write(f,f.relative_to(staging).as_posix())
    lock={'schema':1,'platform':'windows-x64','version':a.version,'pythonVersion':PYTHON_VERSION,
        'archiveUrl':f'https://github.com/danhol86/ios-sweet/releases/download/{a.version}/{archive.name}',
        'archiveBytes':archive.stat().st_size,'archiveSha256':digest(archive),'inventorySha256':digest(inventory_path)}
    (output/'runtime-lock.json').write_text(json.dumps(lock,indent=2)+'\n')
    archive.with_suffix('.zip.sha256').write_text(lock['archiveSha256']+'  '+archive.name+'\n')
    print(json.dumps(lock,indent=2),flush=True)


if __name__=='__main__':main()
