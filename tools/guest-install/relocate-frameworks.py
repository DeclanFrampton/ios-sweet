#!/usr/bin/env python3
"""Resolve a staged QEMU development bundle's embedded library paths.

SWEET's development platform loader may prohibit @rpath expansion. Rewrite
ONLY references to libraries actually embedded in this local app copy to
its fixed /Applications path, then re-sign the complete bundle. This does
not modify dyld, the kernel, system frameworks, or the user's original IPA.
"""
import argparse
from pathlib import Path, PurePosixPath
import struct
import subprocess


DYLIB_COMMANDS={0xC,0xD,0x80000018,0x8000001F,0x20,0x80000023}
RPATH=0x8000001C


def load_names(data):
    if len(data)<32 or data[:4]!=b'\xcf\xfa\xed\xfe':return []
    count,total=struct.unpack_from('<II',data,16)
    if count>4096 or total>len(data)-32:raise ValueError('Invalid Mach-O load commands')
    at=32;result=[]
    for _ in range(count):
        if at+8>32+total:raise ValueError('Truncated Mach-O command')
        command,size=struct.unpack_from('<II',data,at)
        if size<8 or at+size>32+total:raise ValueError('Invalid Mach-O command size')
        if command in DYLIB_COMMANDS or command==RPATH:
            if size<12:raise ValueError('Missing library name offset')
            offset=struct.unpack_from('<I',data,at+8)[0]
            if not 12<=offset<size:raise ValueError('Invalid library name offset')
            name=data[at+offset:at+size].split(b'\0',1)[0].decode('utf-8')
            result.append((command,name))
        at+=size
    return result


def guest_reference(name,image,root):
    root=root.resolve();image=image.resolve()
    if name.startswith('@rpath/'):
        target=root/'Frameworks'/name.removeprefix('@rpath/')
    elif name.startswith('@executable_path/'):
        target=root/name.removeprefix('@executable_path/')
    elif name.startswith('@loader_path/'):
        target=image.parent/name.removeprefix('@loader_path/')
    elif name.startswith('@'):
        raise ValueError('Unsupported relative library reference')
    else:return None
    target=target.resolve()
    try:relative=target.relative_to(root)
    except ValueError:raise ValueError('Library reference escapes staged app') from None
    if not target.is_file():raise ValueError('Referenced embedded library is missing: '+relative.as_posix())
    return str(PurePosixPath('/Applications/iOSNova.app')/relative.as_posix())


def relocate(root,tool):
    root=Path(root).resolve()
    if root.name!='iOSNova.app' or not (root/'Info.plist').is_file():
        raise ValueError('Expected the explicit private iOSNova test bundle')
    changed=0
    for image in sorted(root.rglob('*')):
        if image.is_symlink():raise ValueError('Symlink is not allowed in this isolated bundle')
        if not image.is_file():continue
        with image.open('rb') as handle:header=handle.read(32)
        if header[:4]!=b'\xcf\xfa\xed\xfe':continue
        commands=load_names(image.read_bytes());arguments=[]
        for command,name in commands:
            if command==RPATH:continue
            new=guest_reference(name,image,root)
            if new is not None:
                arguments+=['-id',new] if command==0xD else ['-change',name,new]
        if any(command==RPATH for command,_ in commands):arguments+=['-delete_all_rpaths']
        if not arguments:continue
        subprocess.run([str(tool),*arguments,str(image)],check=True)
        verified=load_names(image.read_bytes())
        if any(name.startswith('@') for _,name in verified):
            raise ValueError('A staged image still requires relative library expansion')
        changed+=1
        print('RELOCATED_LOCAL_APP_IMAGE',image.relative_to(root).as_posix(),flush=True)
    return changed


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('staged_bundle',type=Path)
    p.add_argument('--tool',type=Path,default=Path('/usr/lib/llvm-23/bin/llvm-install-name-tool'))
    a=p.parse_args();print('LOCAL_BUNDLE_IMAGES_RELOCATED',relocate(a.staged_bundle,a.tool))
