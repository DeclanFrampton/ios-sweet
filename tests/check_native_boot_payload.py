"""Exercise Studio's actual child-tool chain without starting QEMU or using iOS.

Builds a synthetic product tree and sparse dummy disk. The project XNU kernel
is the public open-source build. This tests mkadt -> mkpayload -> RAM image,
NOT iOS first boot; no Apple firmware is included in this check.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'desktop')]
import adt
import mkadt
import runtime_setup


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assets',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();asset=args.assets.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='native payload ',dir=out) as temp:
        work=Path(temp);tree=work/'synthetic-product.adt';disk=work/'empty.raw'
        root=mkadt.node('device-tree',[],[mkadt.node('product',[
            ('artwork-display-gamut',b'P3\0'),('test-only-padding',b'\0'*16384)])])
        tree.write_bytes(adt.serialize(root))
        before=hashlib.sha256(tree.read_bytes()).hexdigest()
        subprocess.run([str(asset/'qemu/qemu-img.exe'),'create','-f','raw',str(disk),'16G'],
            capture_output=True,check=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        environment=dict(os.environ,IOS_SWEET_QEMU_DIR=str(asset/'qemu'),IOS_SWEET_DATA_ROOT=str(work),
            SWEET_QEMU_PRODUCT_ADT=str(work/'developer-research-is-not-present.adt'))
        command=[sys.executable,str(ROOT/'desktop/source_entry.py'),'--tool','iossweet-native-windows.py',
            '--prepare-only','--kernel',str(asset/'kernel.aks-quiet.sweet'),'--kernel-sha256',runtime_setup.QUIET_KERNEL,
            '--disk',str(disk),'--overlay',str(work/'not-created.qcow2'),'--state',str(work/'state'),
            '--product-adt',str(tree),'--product-adt-sha256',before,'--cpus','2','--srgb-display','--no-browser']
        result=subprocess.run(command,env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=150,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (out/'boot-payload.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        if result.returncode:raise RuntimeError('Native boot payload test failed: '+result.stderr[-2000:])
        runs=list((work/'state').glob('windows-qemu-*'))
        if len(runs)!=1:raise RuntimeError('Expected one isolated native preparation run')
        run=runs[0]
        for name in ('qemu.adt','payload.bin','ram.bin','stub.bin','mkadt.log','mkpayload.log'):
            if not (run/name).is_file():raise RuntimeError('Missing generated boot component: '+name)
        if (run/'payload.bin').read_bytes()[:8]!=b'SWEETXNU':raise RuntimeError('Invalid native payload')
        generated,_=adt.parse((run/'qemu.adt').read_bytes())
        if next(n for n in generated.children if n.name=='product').prop('artwork-display-gamut')!=b'sRGB\0':
            raise RuntimeError('Explicit product capabilities were not used')
        if hashlib.sha256(tree.read_bytes()).hexdigest()!=before:raise RuntimeError('Source tree was modified')
        if (work/'not-created.qcow2').exists():raise RuntimeError('Prepare-only changed the disk overlay')
        summary={'status':'native-boot-payload-passed','sourceTreeUnchanged':True,'noGuestStarted':True,
            'usedDeveloperResearch':False,'adtBytes':(run/'qemu.adt').stat().st_size,'payloadBytes':(run/'payload.bin').stat().st_size}
        (out/'acceptance.json').write_text(json.dumps(summary,indent=2))
        print('NATIVE_BOOT_PAYLOAD_PASS '+json.dumps(summary),flush=True)


if __name__=='__main__':main()
