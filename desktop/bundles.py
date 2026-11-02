"""Untrusted IPA validation, private-copy preparation and streaming transport.

No extracted executable is run on Windows. No Apple keys or remote signing.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import zipfile

MAX_BYTES = 4 * 1024**3
MAX_FILES = 50000
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9.-]{1,179}\Z')
DYLIBS = {0xC, 0xD, 0x80000018, 0x8000001F, 0x20, 0x80000023}
MAGICS = (b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf')
RESERVED = {'CON','PRN','AUX','NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024**2), b''): h.update(chunk)
    return h.hexdigest()


def bundle_id(value: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value) or '.' not in value or '..' in value or value.endswith('.') or value.lower().startswith('com.apple.'):
        raise ValueError('Expected a non-Apple reverse-domain bundle identifier.')
    return value


def safe_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or len(value)>1024 or any(c in value for c in '\\:\x00<>"|?*') or value.startswith('/'):
        raise ValueError('Unsafe archive path.')
    parts = value.rstrip('/').split('/')
    for p in parts:
        if not p or p in ('.','..') or p.rstrip(' .')!=p or p.split('.')[0].upper() in RESERVED or any(ord(c)<32 for c in p):
            raise ValueError('Unsafe or Windows-reserved archive path: '+value)
    return PurePosixPath(*parts)


def arm64(data: bytes) -> bytes:
    if data[:4] in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
        wide=data[:4]==b'\xca\xfe\xba\xbf'
        if len(data)<8: raise ValueError('Truncated universal Mach-O.')
        n=struct.unpack_from('>I',data,4)[0]; width=32 if wide else 20
        if not 0<n<65 or 8+n*width>len(data): raise ValueError('Invalid universal Mach-O.')
        matches=[]
        for i in range(n):
            cpu,sub=struct.unpack_from('>II',data,8+i*width)
            off,size=struct.unpack_from('>QQ' if wide else '>II',data,16+i*width)
            if off<8+n*width or size<32 or off+size>len(data):raise ValueError('Invalid Mach-O slice.')
            if cpu==0x100000c and sub&0xffffff==0:matches.append(data[off:off+size])
        if len(matches)!=1:raise ValueError('IPA requires exactly one ordinary arm64 iOS slice (not arm64e or simulator).')
        data=matches[0]
    if len(data)<32 or data[:4]!=b'\xcf\xfa\xed\xfe':raise ValueError('Not a 64-bit iOS Mach-O.')
    cpu,sub=struct.unpack_from('<II',data,4)
    if cpu!=0x100000c or sub&0xffffff!=0:raise ValueError('This guest needs arm64 device code, not arm64e, Intel or simulator code.')
    for cmd,block in commands(data):
        if cmd in (0x21,0x2c) and len(block)>=20 and struct.unpack_from('<I',block,16)[0]:
            raise ValueError('Encrypted App Store binary: use your own unencrypted development/export IPA. DRM is not removed.')
        if cmd==0x32:
            platform,minimum=struct.unpack_from('<II',block,8)
            if platform!=2:raise ValueError('This is not an iOS-device binary (simulator/macOS builds cannot run here).')
            if minimum>0x100710:raise ValueError('App or framework requires newer than iOS 16.7.16.')
        if cmd==0x25 and struct.unpack_from('<I',block,8)[0]>0x100710:
            raise ValueError('App requires newer than iOS 16.7.16.')
    return data


def commands(data: bytes):
    if len(data)<32:raise ValueError('Truncated Mach-O.')
    count,total=struct.unpack_from('<II',data,16)
    if count>4096 or total>len(data)-32:raise ValueError('Invalid Mach-O command table.')
    at=32
    for _ in range(count):
        if at+8>32+total:raise ValueError('Truncated Mach-O command.')
        cmd,size=struct.unpack_from('<II',data,at)
        if size<8 or at+size>32+total:raise ValueError('Invalid Mach-O command length.')
        yield cmd,data[at:at+size];at+=size


def inspect_ipa(path: Path) -> dict:
    path=Path(path)
    if path.suffix.lower()!='.ipa' or not path.is_file() or path.stat().st_size>MAX_BYTES:
        raise ValueError('Select a local IPA no larger than 4 GiB.')
    with zipfile.ZipFile(path) as z:
        entries=z.infolist()
        if not 1<=len(entries)<=MAX_FILES:raise ValueError('Archive contains too many files.')
        seen=set();total=0
        for e in entries:
            safe_path(e.filename)
            key=e.filename.rstrip('/').casefold()
            if key in seen:raise ValueError('Duplicate or case-colliding ZIP path.')
            seen.add(key)
            kind=stat.S_IFMT(e.external_attr>>16)
            if kind not in (0,stat.S_IFREG,stat.S_IFDIR):raise ValueError('Symlinks and special files are not accepted.')
            if e.flag_bits&1:raise ValueError('Password-protected archives are not supported.')
            total+=e.file_size
            if total>MAX_BYTES:raise ValueError('Expanded IPA exceeds 4 GiB.')
        infos=[e for e in entries if re.fullmatch(r'Payload/[^/]+\.app/Info\.plist',e.filename)]
        if len(infos)!=1 or infos[0].file_size>4*1024**2:raise ValueError('Expected one app with a bounded Info.plist.')
        info=plistlib.loads(z.read(infos[0]));bid=bundle_id(info.get('CFBundleIdentifier'))
        root=infos[0].filename.rsplit('/',1)[0];exe=info.get('CFBundleExecutable','')
        if '/' in exe or str(safe_path(exe))!=exe:raise ValueError('Invalid app executable name.')
        version=tuple(int(p) for p in str(info.get('MinimumOSVersion','0')).split('.'))
        if version>(16,7,16):raise ValueError('IPA requires newer than iOS 16.7.16.')
        ex=z.getinfo(root+'/'+exe)
        if ex.file_size>256*1024**2:raise ValueError('Main executable exceeds the 256 MiB inspection limit.')
        arm64(z.read(ex))
        return {'bundleId':bid,'name':str(info.get('CFBundleDisplayName',info.get('CFBundleName',bid)))[:180],
            'version':str(info.get('CFBundleShortVersionString','1.0'))[:80], 'minimumOS':str(info.get('MinimumOSVersion','unknown')),
            'executable':exe,'root':root,'expandedBytes':total,'sourceSha256':sha256(path),
            'guestPath':'/Applications/IOSSweet-'+bid+'.app',
            'warnings':['App extensions are not separately registered.' ] if any(e.filename.startswith(root+'/PlugIns/') for e in entries) else []}


def prepare(path: Path, job: Path, signer: Path, report=print) -> tuple[dict, Path]:
    info=inspect_ipa(path);job=Path(job);job.mkdir(parents=True,exist_ok=True)
    root=job/('IOSSweet-'+info['bundleId']+'.app')
    if root.exists():raise ValueError('Preparation directory already exists; original files were not overwritten.')
    root.mkdir()
    report('Extracting validated IPA into a private copy')
    with zipfile.ZipFile(path) as z:
        prefix=info['root']+'/'
        for e in z.infolist():
            if not e.filename.startswith(prefix) or e.is_dir():continue
            rel=safe_path(e.filename[len(prefix):]);dest=root.joinpath(*rel.parts)
            dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(e) as source,dest.open('xb') as target:shutil.copyfileobj(source,target,1024**2)
    for p in root.rglob('Info.plist'):
        if p.stat().st_size>4*1024**2:raise ValueError('Oversized nested Info.plist.')
        p.write_bytes(plistlib.dumps(plistlib.loads(p.read_bytes()),fmt=plistlib.FMT_BINARY))
    report('Checking and preparing embedded arm64 libraries')
    import lief
    for p in sorted(root.rglob('*')):
        if not p.is_file():continue
        with p.open('rb') as f:magic=f.read(4)
        if magic not in MAGICS:continue
        if p.stat().st_size>256*1024**2:raise ValueError('Mach-O exceeds 256 MiB: '+p.name)
        data=arm64(p.read_bytes());p.write_bytes(data)
        parsed=lief.MachO.parse(str(p))
        if not parsed or len(parsed)!=1:raise ValueError('Cannot parse embedded Mach-O: '+p.name)
        binary=parsed.at(0);changed=False
        for lib in binary.libraries:
            name=lib.name
            if name.startswith('@rpath/'):target=root/'Frameworks'/name[7:]
            elif name.startswith('@loader_path/'):target=p.parent/name[13:]
            elif name.startswith('@executable_path/'):target=root/name[17:]
            elif name.startswith('@'):raise ValueError('Unsupported library path: '+name)
            else:continue
            target=target.resolve()
            try:rel=target.relative_to(root.resolve())
            except ValueError:raise ValueError('Library reference escapes app.') from None
            if not target.is_file():raise ValueError('Missing embedded library: '+rel.as_posix())
            lib.name=info['guestPath']+'/'+rel.as_posix();changed=True
        for cmd in list(binary.commands):
            if isinstance(cmd,lief.MachO.RPathCommand):binary.remove(cmd);changed=True
        if changed:
            binary.remove_signature();binary.write(str(p)+'.rewritten');os.replace(str(p)+'.rewritten',p)
            # Verify the write produced the promised image, before signing.
            for cmd,block in commands(arm64(p.read_bytes())):
                if cmd in DYLIBS or cmd==0x8000001c:
                    off=struct.unpack_from('<I',block,8)[0]
                    if block[off:off+1]==b'@':raise ValueError('Library relocation did not complete.')
    report('Signing the private copy locally (no Apple credentials)')
    result=subprocess.run([str(signer),'sign','--timestamp-url','none',str(root)],capture_output=True,text=True,
        timeout=900,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (job/'signing.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError('Local signing failed. See the job signing.log; original IPA is unchanged.')
    if not (root/'_CodeSignature/CodeResources').is_file():raise RuntimeError('Signer did not seal the app bundle.')
    for p in root.rglob('*'):
        if p.is_file():
            with p.open('rb') as f:magic=f.read(4)
            if magic==MAGICS[0] and not any(cmd==0x1d for cmd,_ in commands(p.read_bytes())):
                raise RuntimeError('Embedded executable has no signature: '+p.name)
    report('Packaging checksum-verified transfer')
    files=[]
    for p in sorted(root.rglob('*')):
        if not p.is_file():continue
        with p.open('rb') as f:magic=f.read(4)
        files.append({'path':p.relative_to(root).as_posix(),'size':p.stat().st_size,
            'mode':0o755 if magic in MAGICS else 0o644,'sha256':sha256(p)})
    manifest=json.dumps({'version':1,'bundleId':info['bundleId'],'files':files},separators=(',',':')).encode()
    packet=job/'transfer.bin'
    with packet.open('xb') as out:
        out.write(struct.pack('>I',len(manifest)));out.write(manifest)
        for f in files:
            with root.joinpath(*PurePosixPath(f['path']).parts).open('rb') as source:shutil.copyfileobj(source,out,1024**2)
    if packet.stat().st_size>MAX_BYTES:raise ValueError('Transfer exceeds 4 GiB.')
    (job/'app.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    return info,packet
