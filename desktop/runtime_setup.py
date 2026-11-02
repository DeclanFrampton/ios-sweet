"""Portable native-Windows device preparation. Docker is a developer build tool only.

Apple firmware is fetched directly over HTTPS or supplied by the owner.
One short-lived, networkless x86 QEMU appliance constructs the private HFSX
disk. The iOS runtime itself is native Windows ARM64 QEMU.
"""
from __future__ import annotations
import contextlib
import hashlib
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
from preparation_log import PreparationLog, monitor
import preparation_initrd

QUIET_KERNEL='7dc86497ccd0c224ec1e6b8430be6f2dd7a46ac13ef795ed4047d0adf7d3bde8'
HIDDEN=getattr(subprocess,'CREATE_NO_WINDOW',0)


def firmware_metadata(firmware,diagnostic):
    """Preserve file lengths: a compressed UDIF is not a sector-aligned APFS disk.

    QEMU rounds raw-device lengths to 512-byte sectors. DMG readers find their
    `koly` trailer relative to the *original* EOF, so hand the exact byte length
    and digest to the appliance instead of treating every .dmg as raw APFS.
    """
    if set(firmware)!={'os','sysos','appos'}:raise ValueError('Expected all three Apple firmware images')
    metadata={}
    for name in ('os','sysos','appos'):
        path=Path(firmware[name]);size=path.stat().st_size
        if not 512<=size<=16*1024**3:raise ValueError('Unexpected Apple firmware size: '+name)
        diagnostic.stage('Verifying '+name+' firmware format and exact byte length')
        with path.open('rb') as f:
            head=f.read(64);f.seek(-512,2);footer=f.read(512)
            if footer[:4]==b'koly':kind='udif'
            elif head[32:36]==b'NXSB' and size%512==0:kind='apfs'
            else:raise ValueError('Unsupported or damaged Apple firmware image: '+name)
            f.seek(0);digest=hashlib.sha256();read=0;stamp=time.monotonic()
            for chunk in iter(lambda:f.read(4*1024**2),b''):
                digest.update(chunk);read+=len(chunk)
                if time.monotonic()-stamp>=5:
                    diagnostic.write('Verified '+name+': '+str(read)+' / '+str(size)+' bytes',publish=True);stamp=time.monotonic()
        if read!=size:raise RuntimeError('Firmware changed while being checked: '+name)
        metadata[name]={'kind':kind,'size':size,'sha256':digest.hexdigest()}
        diagnostic.write(name+': '+kind+', '+str(size)+' exact bytes; source stays read-only',publish=True)
    return metadata


def asset_paths(resource: Path):
    override=os.environ.get('IOS_SWEET_ASSET_ROOT')
    asset=Path(override).resolve() if override else resource/'desktop/assets'
    if not override and not asset.is_dir():asset=resource/'windows-runtime/desktop-build/assets'
    qemu=asset/'qemu'
    if not override and not qemu.is_dir():qemu=resource/'windows-runtime/qemu'
    required=('prepare-kernel','prepare-initrd.gz','iossweet-agent','iossweet-net-seed','kernel.aks-quiet.sweet','lzfse.exe')
    manifest=json.loads((asset/'manifest.json').read_text())
    for name in required:
        p=asset/name
        if not p.is_file() or sha256(p)!=manifest.get(name):
            raise RuntimeError('Missing or changed setup component: '+name+'. Update with git pull --ff-only and start.cmd; keep your device data.')
    if sha256(asset/'kernel.aks-quiet.sweet')!=QUIET_KERNEL:raise RuntimeError('Unexpected iOS kernel.')
    for exe in ('qemu-system-aarch64.exe','qemu-system-x86_64.exe','qemu-img.exe'):
        if not (qemu/exe).is_file():raise RuntimeError('Native QEMU component missing: '+exe)
    for name in ('bios-256k.bin','linuxboot_dma.bin','multiboot_dma.bin','pvh.bin'):
        if not (qemu/'share'/name).is_file():
            raise RuntimeError('The setup runtime is missing QEMU boot firmware '+name+
                '. Update this checkout with git pull and run start.cmd to download the repaired runtime. Your device data is unchanged.')
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


def prepare(root: Path,asset: Path,qemu: Path,mode: str,report,firmware=None,diagnostic=None,resource=None):
    own=diagnostic is None
    diagnostic=diagnostic or PreparationLog(root.parent.parent,mode,report)
    with diagnostic if own else contextlib.nullcontext(diagnostic):
        return _prepare(root,asset,qemu,mode,diagnostic,firmware,resource)


def _prepare(root,asset,qemu,mode,diagnostic,firmware,resource):
    idle();token=secrets.token_hex(32);instance=str(uuid.uuid4())
    images=firmware_metadata(firmware,diagnostic) if mode=='full' else None
    diagnostic.stage('Creating private setup job and logging-enabled boot image')
    job=root/('setup-input-'+uuid.uuid4().hex);job.mkdir()
    for name in ('iossweet-agent','iossweet-net-seed'):shutil.copy2(asset/name,job/name)
    data={'schema':1,'mode':mode,'token':token,'instanceId':instance,
        'hashes':{name:sha256(job/name) for name in ('iossweet-agent','iossweet-net-seed')}}
    if images:data['firmware']=images
    (job/'job.json').write_text(json.dumps(data))
    resource=Path(resource) if resource else Path(__file__).resolve().parents[1]
    initrd=preparation_initrd.build(asset/'prepare-initrd.gz',resource,job/'prepare-logged-initrd.gz')
    # The FAT job volume should not include the large initrd (QEMU's FAT
    # driver otherwise has to map that unrelated file). Keep it beside it.
    boot=root/('prepare-boot-'+uuid.uuid4().hex+'.gz');os.replace(initrd,boot)
    (root/'preparation-log.txt').write_text(str(diagnostic.path),encoding='utf-8')
    diagnostic.write('Device workspace: '+str(root),publish=True)
    diagnostic.write('Full timestamped log: '+str(diagnostic.path),publish=True)
    target=root/('ios.qcow2' if mode=='seed' else 'ios.raw')
    def slash(p):
        p=str(p).replace('\\','/')
        if ',' in p:raise ValueError('The QEMU preparation directory must not contain commas.')
        return p
    cmd=[str(qemu/'qemu-system-x86_64.exe'),'-machine','q35','-accel','tcg,thread=multi','-smp','2','-m','1536',
        '-display','none','-monitor','none','-serial','stdio','-no-reboot','-nic','none',
        '-kernel',str(asset/'prepare-kernel'),'-initrd',str(boot),
        '-append','console=ttyS0 rdinit=/init panic=-1 loglevel=6 printk.time=1',
        '-drive',f'file={slash(target)},format={"qcow2" if mode=="seed" else "raw"},if=virtio,cache=writeback',
        '-drive',f'file=fat:ro:{slash(job)},format=raw,if=virtio,readonly=on']
    if mode=='full':
        for name in ('os','sysos','appos'):
            cmd+=['-drive',f'file={slash(firmware[name])},format=raw,if=virtio,readonly=on']
    try:
        monitor(cmd,diagnostic,'Booting the offline disk-preparation engine',timeout=7200,
            success_marker='STUDIO_PREPARER_SUCCESS')
    finally:
        # These are exclusively this run's newly created setup files. Do not
        # remove the diagnostic log, downloaded firmware, source or target disk.
        boot.unlink(missing_ok=True)
        if job.parent.resolve()!=root.resolve() or job.is_symlink():raise RuntimeError('Unexpected setup cleanup path')
        shutil.rmtree(job)
    if mode=='full':
        monitor([str(qemu/'qemu-img.exe'),'create','-f','qcow2','-F','raw','-b',str(root/'ios.raw'),str(root/'ios.qcow2')],
            diagnostic,'Creating the writable iPhone overlay',timeout=120)
    diagnostic.stage('Saving the verified device configuration')
    result=config(root,asset,qemu,token,instance)
    diagnostic.write('Private device verified; setup secrets removed from the temporary input folder',publish=True)
    return result


def from_prepared_root(source: Path,home: Path,resource: Path,report=print):
    source=source.resolve(strict=True)
    if source.is_symlink() or not source.is_file() or source.stat().st_size!=16*1024**3:
        raise ValueError('Expected a prepared 16 GiB iOS Sweet HFSX raw image.')
    with source.open('rb') as f:
        f.seek(1024)
        if f.read(2) not in (b'HX',b'H+'):raise ValueError('Image is not HFSX/HFS+. An IPSW or APFS image cannot be imported here.')
    with PreparationLog(home,'import',report) as diagnostic:
        diagnostic.stage('Checking preparation components and available storage')
        asset,qemu=asset_paths(resource);root=directory(home)
        monitor([str(qemu/'qemu-img.exe'),'convert','-p','-f','raw','-O','raw','-S','4k',str(source),str(root/'ios.raw')],
            diagnostic,'Copying the prepared image; original stays untouched',timeout=1800)
        monitor([str(qemu/'qemu-img.exe'),'create','-f','qcow2','-F','raw','-b',str(root/'ios.raw'),str(root/'ios.qcow2')],
            diagnostic,'Creating the private writable overlay',timeout=120)
        return prepare(root,asset,qemu,'seed',report,diagnostic=diagnostic,resource=resource)


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
    with PreparationLog(home,'download',report) as diagnostic:
        diagnostic.stage('Checking preparation components and available storage')
        asset,qemu=asset_paths(resource)
        import product_tree
        diagnostic.stage('Preparing the private iPhone product device tree')
        product=product_tree.ensure(home,resource,diagnostic)
        if shutil.disk_usage(home).free<35*1024**3:raise RuntimeError('Downloading and preparing iOS needs at least 35 GB free.')
        root=directory(home);cache=home/'firmware-cache';cache.mkdir(exist_ok=True)
        sys.path.insert(0,str(resource/'tools'))
        spec=importlib.util.spec_from_file_location('studio_apple_firmware',resource/'tools/AutoPrepare-IosSweet.py')
        apple=importlib.util.module_from_spec(spec);spec.loader.exec_module(apple)
        diagnostic.stage('Downloading and checking iPhone X iOS 16.7.16 from Apple')
        with contextlib.redirect_stdout(ProgressWriter(diagnostic)):
            dest,entries,wanted=apple.get_manifest(cache)
            firmware={name:apple.extract_member(dest,entries,wanted[name]) for name in ('os','sysos','appos')}
        monitor([str(qemu/'qemu-img.exe'),'create','-f','raw',str(root/'ios.raw'),'16G'],
            diagnostic,'Allocating the private iOS disk',timeout=120)
        result=prepare(root,asset,qemu,'full',report,firmware,diagnostic=diagnostic,resource=resource)
        result.update(productAdt=str(product),productAdtSha256=product_tree.ADT_SHA256)
        return result
