"""Portable native-Windows device preparation. Docker is a developer build tool only.

Apple firmware is fetched directly over HTTPS or supplied by the owner.
One short-lived, networkless x86 QEMU appliance constructs the private HFSX
disk. The iOS runtime itself is native Windows ARM64 QEMU.
"""
from __future__ import annotations
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import uuid

from bundles import sha256

QUIET_KERNEL='7dc86497ccd0c224ec1e6b8430be6f2dd7a46ac13ef795ed4047d0adf7d3bde8'
HIDDEN=getattr(subprocess,'CREATE_NO_WINDOW',0)


def asset_paths(resource: Path):
    asset=resource/'desktop/assets'
    if not asset.is_dir():asset=resource/'windows-runtime/desktop-build/assets'
    qemu=asset/'qemu'
    if not qemu.is_dir():qemu=resource/'windows-runtime/qemu'
    required=('prepare-kernel','prepare-initrd.gz','iossweet-agent','iossweet-net-seed','kernel.aks-quiet.sweet')
    manifest=json.loads((asset/'manifest.json').read_text())
    for name in required:
        p=asset/name
        if not p.is_file() or sha256(p)!=manifest.get(name):raise RuntimeError('Missing or changed setup component: '+name)
    if sha256(asset/'kernel.aks-quiet.sweet')!=QUIET_KERNEL:raise RuntimeError('Unexpected iOS kernel.')
    for exe in ('qemu-system-aarch64.exe','qemu-system-x86_64.exe','qemu-img.exe'):
        if not (qemu/exe).is_file():raise RuntimeError('Native QEMU component missing: '+exe)
    return asset,qemu


def idle():
    r=subprocess.run(['tasklist','/FI','IMAGENAME eq qemu-system-aarch64.exe','/FO','CSV','/NH'],capture_output=True,text=True,timeout=15,creationflags=HIDDEN)
    if r.returncode or 'qemu-system-aarch64.exe' in r.stdout.lower():
        raise RuntimeError('Stop the existing iPhone before creating a device. It has not been changed.')


def directory(home: Path):
    idle()
    if shutil.disk_usage(home).free<24*1024**3:raise RuntimeError('At least 24 GB of free storage is required to create a device.')
    root=home/'devices'/uuid.uuid4().hex
    root.mkdir(parents=True);(root/'state').mkdir()
    return root


def config(root: Path,asset: Path,qemu: Path,token: str,instance: str):
    bridge=root/'bridge.json'
    bridge.write_text(json.dumps({'Token':token,'InstanceId':instance,'BundleId':'com.iosnova','BundlePath':'/Applications/iOSNova.app'}))
    # Windows user-profile ACLs are inherited; never place credentials in ProgramData or a public web directory.
    return {'schema':2,'disk':str(root/'ios.raw'),'overlay':str(root/'ios.qcow2'),
        'kernel':str(asset/'kernel.aks-quiet.sweet'),'kernelSha256':QUIET_KERNEL,
        'bridgeConfig':str(bridge),'state':str(root/'state'),'qemu':str(qemu),
        'viewerPort':8108,'qmpPort':4444,'instanceId':instance}


def prepare(root: Path,asset: Path,qemu: Path,mode: str,report,firmware=None):
    idle();token=secrets.token_hex(32);instance=str(uuid.uuid4())
    job=root/('setup-input-'+uuid.uuid4().hex);job.mkdir()
    for name in ('iossweet-agent','iossweet-net-seed'):shutil.copy2(asset/name,job/name)
    data={'schema':1,'mode':mode,'token':token,'instanceId':instance,
        'hashes':{name:sha256(job/name) for name in ('iossweet-agent','iossweet-net-seed')}}
    (job/'job.json').write_text(json.dumps(data))
    target=root/('ios.qcow2' if mode=='seed' else 'ios.raw')
    def slash(p):
        p=str(p).replace('\\','/')
        if ',' in p:raise ValueError('The QEMU preparation directory must not contain commas.')
        return p
    cmd=[str(qemu/'qemu-system-x86_64.exe'),'-machine','q35','-accel','tcg,thread=multi','-smp','2','-m','1536',
        '-display','none','-monitor','none','-serial','stdio','-no-reboot','-nic','none',
        '-kernel',str(asset/'prepare-kernel'),'-initrd',str(asset/'prepare-initrd.gz'),
        '-append','console=ttyS0 rdinit=/init panic=-1 quiet',
        '-drive',f'file={slash(target)},format={"qcow2" if mode=="seed" else "raw"},if=virtio,cache=writeback',
        '-drive',f'file=fat:ro:{slash(job)},format=raw,if=virtio,readonly=on']
    if mode=='full':
        for name in ('os','sysos','appos'):
            cmd+=['-drive',f'file={slash(firmware[name])},format=raw,if=virtio,readonly=on']
    log=root/'prepare.log';report('Preparing your private iOS disk with the native offline setup engine')
    with log.open('w',encoding='utf-8') as out:
        process=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',creationflags=HIDDEN)
        deadline=time.monotonic()+7200;success=False
        # Stream bounded log lines. A watchdog terminates only this owned setup process.
        def watchdog():
            while process.poll() is None and time.monotonic()<deadline:time.sleep(2)
            if process.poll() is None:process.terminate()
        import threading
        threading.Thread(target=watchdog,daemon=True).start()
        for line in process.stdout:
            out.write(line);out.flush()
            if any(mark in line for mark in ('STUDIO_','COPYING ','ASSEMBLING_','PRIVATE_MG_','PREPARE_STEP')):
                report(line.strip()[:500])
            if line.strip()=='STUDIO_PREPARER_SUCCESS':success=True
        rc=process.wait(timeout=20)
    if rc or not success:raise RuntimeError('Local device preparation failed. See '+str(log)+'. The source image was not changed.')
    if mode=='full':
        subprocess.run([str(qemu/'qemu-img.exe'),'create','-f','qcow2','-F','raw','-b',str(root/'ios.raw'),str(root/'ios.qcow2')],
            check=True,capture_output=True,creationflags=HIDDEN)
    result=config(root,asset,qemu,token,instance)
    shutil.rmtree(job)  # exclusively this freshly created, per-job directory
    report('Private device verified; setup secrets removed from the temporary input folder')
    return result


def from_prepared_root(source: Path,home: Path,resource: Path,report=print):
    source=source.resolve(strict=True)
    if source.is_symlink() or not source.is_file() or source.stat().st_size!=16*1024**3:
        raise ValueError('Expected a prepared 16 GiB iOS Sweet HFSX raw image.')
    with source.open('rb') as f:
        f.seek(1024)
        if f.read(2) not in (b'HX',b'H+'):raise ValueError('Image is not HFSX/HFS+. An IPSW or APFS image cannot be imported here.')
    asset,qemu=asset_paths(resource);root=directory(home)
    report('Creating a private sparse copy; the original image stays untouched')
    subprocess.run([str(qemu/'qemu-img.exe'),'convert','-f','raw','-O','raw','-S','4k',str(source),str(root/'ios.raw')],
        check=True,capture_output=True,timeout=1800,creationflags=HIDDEN)
    subprocess.run([str(qemu/'qemu-img.exe'),'create','-f','qcow2','-F','raw','-b',str(root/'ios.raw'),str(root/'ios.qcow2')],
        check=True,capture_output=True,creationflags=HIDDEN)
    return prepare(root,asset,qemu,'seed',report)


class ProgressWriter:
    def __init__(self,report):self.report=report;self.buffer=''
    def write(self,text):
        self.buffer+=text
        while '\n' in self.buffer:
            line,self.buffer=self.buffer.split('\n',1)
            if line.strip():self.report(line.strip())
        return len(text)
    def flush(self):pass


def from_apple(home: Path,resource: Path,report=print):
    asset,qemu=asset_paths(resource)
    if shutil.disk_usage(home).free<35*1024**3:raise RuntimeError('Downloading and preparing iOS needs at least 35 GB free.')
    root=directory(home);cache=home/'firmware-cache';cache.mkdir(exist_ok=True)
    sys.path.insert(0,str(resource/'tools'))
    spec=importlib.util.spec_from_file_location('studio_apple_firmware',resource/'tools/AutoPrepare-IosSweet.py')
    apple=importlib.util.module_from_spec(spec);spec.loader.exec_module(apple)
    report('Downloading iPhone X iOS 16.7.16 (20H392) directly from Apple')
    with contextlib.redirect_stdout(ProgressWriter(report)):
        dest,entries,wanted=apple.get_manifest(cache)
        firmware={name:apple.extract_member(dest,entries,wanted[name]) for name in ('os','sysos','appos')}
    subprocess.run([str(qemu/'qemu-img.exe'),'create','-f','raw',str(root/'ios.raw'),'16G'],check=True,capture_output=True,creationflags=HIDDEN)
    return prepare(root,asset,qemu,'full',report,firmware)
