"""Build a firmware-free Windows portable app and single-EXE installer.

Run in a clean Windows venv with desktop/requirements.txt installed. Supply
the five checksum-listed helper assets and an audited native QEMU directory.
The release never includes any Apple firmware, private IPA or guest data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from bundles import sha256

QEMU_FILES=('qemu-system-aarch64.exe','qemu-system-x86_64.exe','qemu-img.exe','COPYING','COPYING.LIB','README.rst')
BIOS=('bios-256k.bin','bios.bin','bios-microvm.bin','kvmvapic.bin','vgabios-stdvga.bin','vgabios-virtio.bin','efi-e1000e.rom','efi-e1000.rom','pxe-e1000.rom','pxe-e1000e.rom')
REQUIRED_BOOT=('bios-256k.bin','linuxboot_dma.bin','multiboot_dma.bin','pvh.bin')
ASSETS=('prepare-kernel','prepare-initrd.gz','iossweet-agent','iossweet-net-seed','kernel.aks-quiet.sweet','lzfse.exe')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assets',type=Path,required=True)
    p.add_argument('--qemu',type=Path,required=True)
    p.add_argument('--signer',type=Path,required=True)
    p.add_argument('--output',type=Path,default=ROOT/'windows-runtime/desktop-build/release')
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    staging=out/'payload';staging.mkdir(exist_ok=True)
    tools=staging/'tools';tools.mkdir(exist_ok=True)
    for source in (ROOT/'tools').glob('*.py'):shutil.copy2(source,tools/source.name)
    shutil.copy2(ROOT/'tools/qemu-viewer.html',tools/'qemu-viewer.html')
    (tools/'guest-install').mkdir(exist_ok=True)
    shutil.copy2(ROOT/'tools/guest-install/client.py',tools/'guest-install/client.py')
    ui=staging/'desktop';ui.mkdir(exist_ok=True);shutil.copy2(ROOT/'desktop/index.html',ui/'index.html')
    (ui/'appliance').mkdir(exist_ok=True)
    for name in ('init','prepare.py'):shutil.copy2(ROOT/'desktop/appliance'/name,ui/'appliance'/name)
    assets=ui/'assets';assets.mkdir(exist_ok=True)
    manifest=json.loads((args.assets/'manifest.json').read_text())
    for name in ASSETS:
        source=args.assets/name
        if sha256(source)!=manifest.get(name):raise RuntimeError('Helper hash mismatch: '+name)
        shutil.copy2(source,assets/name)
    shutil.copy2(args.assets/'manifest.json',assets/'manifest.json')
    shutil.copy2(args.signer,assets/'rcodesign.exe')
    if (args.assets/'licenses').exists():shutil.copytree(args.assets/'licenses',assets/'licenses',dirs_exist_ok=True)
    qemu=assets/'qemu';qemu.mkdir(exist_ok=True)
    for name in QEMU_FILES:
        source=args.qemu/name
        if not source.exists():raise RuntimeError('Missing QEMU distribution file: '+name)
        shutil.copy2(source,qemu/name)
    for source in args.qemu.glob('*.dll'):shutil.copy2(source,qemu/source.name)
    (qemu/'share').mkdir(exist_ok=True)
    for name in sorted(set(BIOS+REQUIRED_BOOT)):
        source=args.qemu/'share'/name
        if name in REQUIRED_BOOT and not source.is_file():raise RuntimeError('Missing required setup boot ROM: '+name)
        if source.exists():shutil.copy2(source,qemu/'share'/name)
    for folder in ('licenses','license'):
        if (args.qemu/folder).is_dir():shutil.copytree(args.qemu/folder,qemu/folder,dirs_exist_ok=True)
    notice=ROOT/'desktop/THIRD_PARTY_NOTICES.md'
    if notice.exists():shutil.copy2(notice,staging/notice.name)
    shutil.copy2(ROOT/'LICENSE',staging/'LICENSE')
    # Inventories aid reproducibility without embedding machine-local paths.
    inventory={str(f.relative_to(staging)).replace('\\','/'):sha256(f) for f in staging.rglob('*') if f.is_file()}
    (staging/'runtime-sha256.json').write_text(json.dumps(inventory,indent=2))
    # This staging tree is constructed from an explicit source/asset allowlist.
    forbidden=('.ipa','.raw','.qcow2','.dmg','.p8','.p12','.mobileprovision','.adt','.im4p','.ipsw')
    for f in staging.rglob('*'):
        if f.is_file() and (f.suffix.lower() in forbidden or f.name in ('bridge.json','device.json','host-bridge.json')):
            raise RuntimeError('Private media exclusion failed: '+f.name)
    cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed',
        '--name','iOS Sweet Studio','--paths',str(ROOT/'desktop'),'--paths',str(ROOT/'tools'),
        '--distpath',str(out/'portable'),'--workpath',str(out/'pyinstaller-work'),'--specpath',str(out),
        '--add-data',str(staging)+os.pathsep+'payload']
    for package in ('webview','clr_loader','pythonnet','lief','PIL'):cmd+=['--collect-all',package]
    for module in ('adt','msvcrt','ctypes.wintypes','argparse','datetime','struct','zlib','shlex','fnmatch','csv','lzma','platform'):
        cmd+=['--hidden-import',module]
    cmd+=[str(ROOT/'desktop/studio.py')]
    print('BUILDING_NATIVE_DESKTOP_APPLICATION',flush=True)
    subprocess.run(cmd,check=True)
    portable=out/'portable/iOS Sweet Studio'
    csc=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    common=[str(csc),'/nologo','/target:winexe','/platform:x64','/optimize+',
        '/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Core.dll',
        '/r:Microsoft.CSharp.dll','/r:System.IO.Compression.dll','/r:System.IO.Compression.FileSystem.dll']
    subprocess.run([*common,'/out:'+str(portable/'Uninstall.exe'),str(ROOT/'desktop/installer/Uninstall.cs')],check=True)
    archive=out/'iOS-Sweet-Studio-Windows-x64.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in sorted(portable.rglob('*')):
            if f.is_file():z.write(f,f.relative_to(portable).as_posix())
    payload_hash=out/'payload.sha256';payload_hash.write_text(sha256(archive))
    exe=out/'iOS-Sweet-Studio-Setup.exe'
    subprocess.run([*common,'/out:'+str(exe),'/resource:'+str(archive)+',payload.zip',
        '/resource:'+str(payload_hash)+',payload.sha256',str(ROOT/'desktop/installer/Setup.cs')],check=True)
    for f in (archive,exe):
        f.with_suffix(f.suffix+'.sha256').write_text(sha256(f)+'  '+f.name+'\n')
    print('PUBLIC_PACKAGE_PRIVATE_MEDIA_GATE_PASSED',flush=True)
    print('INSTALLER',exe,exe.stat().st_size,flush=True)
    print('PORTABLE',archive,archive.stat().st_size,flush=True)


if __name__=='__main__':main()
