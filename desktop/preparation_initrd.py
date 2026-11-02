"""Append a tiny source-controlled cpio archive to the verified runtime initrd.

Linux initramfs supports concatenated compressed/uncompressed newc archives:
https://www.kernel.org/doc/html/latest/driver-api/early-userspace/buffer-format.html
Only init and tools/prepare.py are replaced. The public cached runtime remains
unaltered, so source logging fixes take effect after git pull, without Docker.
"""
import gzip
from pathlib import Path
import shutil
import stat


def newc(files):
    out=bytearray()
    for ino,(name,data,mode) in enumerate([*files,('TRAILER!!!',b'',0)],1):
        if name not in ('init','tools/prepare.py','TRAILER!!!'):raise ValueError('Not an allowed preparation overlay file')
        encoded=name.encode()+b'\0'
        fields=(ino,mode,0,0,1,0,len(data),0,0,0,0,len(encoded),0)
        out+=b'070701'+''.join(f'{n:08x}' for n in fields).encode()+encoded
        out+=b'\0'*(-len(out)%4);out+=data;out+=b'\0'*(-len(out)%4)
    return bytes(out)


def build(base,resource,destination):
    destination=Path(destination)
    files=[]
    for source,target,mode in [('init','init',0o755),('prepare.py','tools/prepare.py',0o644)]:
        path=Path(resource)/'desktop/appliance'/source
        if path.stat().st_size>1024**2:raise ValueError('Unexpectedly large preparation script')
        data=path.read_text(encoding='utf-8').replace('\r\n','\n').encode()
        files.append((target,data,stat.S_IFREG|mode))
    with Path(base).open('rb') as src,destination.open('xb') as out:
        shutil.copyfileobj(src,out,1024**2)
        out.write(gzip.compress(newc(files),compresslevel=6,mtime=0))
    return destination
