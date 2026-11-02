"""Runs only inside Studio's offline, networkless Linux preparation appliance.

Disk roles are fixed: vda is a new writable copy; vdb is read-only job FAT;
vdc/vdd/vde (full mode) are Apple's three downloaded read-only APFS images.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time
import re

ROOT=Path('/target')

def stage(message):print('STUDIO_STAGE '+message,flush=True)

def run(*args,timeout=1800):
    print('PREPARE_STEP '+str(args[0]),flush=True)
    # These arguments are fixed setup tools, never profile/signing secrets.
    print('Running: '+' '.join(map(str,args)),flush=True)
    try:subprocess.run(list(map(str,args)),check=True,timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Step timed out after '+str(timeout)+'s: '+str(args[0])) from None

def module(name):
    spec=importlib.util.spec_from_file_location(name,Path('/tools')/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def sha(p):
    h=hashlib.sha256()
    total=p.stat().st_size;done=0;last=time.monotonic()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):
            h.update(b);done+=len(b)
            if time.monotonic()-last>=5:
                print('Checksum read: '+str(done)+' / '+str(total)+' bytes',flush=True);last=time.monotonic()
    return h.hexdigest()

def validate_image_metadata(images):
    if not isinstance(images,dict) or set(images)!={'os','sysos','appos'}:
        raise RuntimeError('Firmware transport metadata is missing. Update the source and retry; cached downloads can be reused.')
    for name,meta in images.items():
        if (not isinstance(meta,dict) or meta.get('kind') not in ('udif','apfs') or
            type(meta.get('size')) is not int or not 512<=meta['size']<=16*1024**3 or
            not isinstance(meta.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',meta['sha256'])):
            raise RuntimeError('Invalid exact-length firmware metadata: '+name)


def copy_exact_firmware(source,destination,meta):
    """Restore the byte-exact regular file from a read-only, padded block device.

    Apple compressed UDIF OS images can end between sectors. APFS-FUSE reads
    the last 512 *file* bytes to identify UDIF; the padded block-device EOF
    silently changes that location. A verified temporary file fixes this
    without changing/decrypting/re-downloading the Apple image.
    """
    size=meta['size'];h=hashlib.sha256();done=0;started=time.monotonic();last=started
    with Path(source).open('rb') as src,Path(destination).open('xb') as dst:
        while done<size:
            chunk=src.read(min(4*1024**2,size-done))
            if not chunk:raise RuntimeError('Read-only firmware transfer ended before its recorded file length')
            dst.write(chunk);h.update(chunk);done+=len(chunk)
            if time.monotonic()-last>=5 or done==size:
                seconds=max(.001,time.monotonic()-started)
                print(str(done)+' '+str(done*100//size)+'% '+str(round(done/seconds/1048576,2))+'MB/s exact DMG copy',flush=True)
                last=time.monotonic()
        dst.flush();os.fsync(dst.fileno())
    if h.hexdigest()!=meta['sha256']:
        raise RuntimeError('Firmware transport SHA-256 mismatch; the original download is unchanged')
    with Path(destination).open('rb') as f:
        f.seek(-512,2)
        if f.read(4)!=b'koly':raise RuntimeError('Exact-length DMG is missing its UDIF trailer')
    print('STUDIO_FIRMWARE_FILE_VERIFIED '+str(size)+' exact bytes; UDIF trailer preserved',flush=True)


def mount_firmware(name,dev,meta):
    src=Path('/firmware')/(name+'.dmg');src.symlink_to(dev)
    scratch=None
    # Restore only compressed images. Raw APFS cryptexes remain directly
    # mounted from read-only block devices, with no extra copies.
    if meta['kind']=='udif':
        stage('Restoring exact '+name+' DMG file; original download stays read-only')
        import uuid
        scratch=ROOT/('.studio-firmware-'+uuid.uuid4().hex+'.dmg')
        if shutil.disk_usage(ROOT).free<meta['size']+256*1024**2:
            raise RuntimeError('Not enough free space in the private disk for temporary firmware staging')
        copy_exact_firmware(src,scratch,meta);src=scratch
    else:
        with src.open('rb') as f:
            if f.read(36)[32:36]!=b'NXSB':raise RuntimeError('Read-only APFS firmware header mismatch: '+name)
    mount=Path('/firmware')/name;mount.mkdir()
    stage('Mounting Apple '+name+' firmware image (read-only)')
    run('/usr/local/bin/apfs-fuse','-o','allow_other',src,mount,timeout=300)
    if not (mount/'root').is_dir():raise RuntimeError('Apple APFS image lacks root directory: '+name)
    return mount,scratch


def populate(images):
    validate_image_metadata(images)
    print('ASSEMBLING_PRIVATE_IOS_ROOT',flush=True)
    stage('Formatting the new private HFSX disk')
    run('/usr/sbin/mkfs.hfsplus','-s','-J','-v','iOSRoot','/dev/vda',timeout=300)
    run('mount','-t','hfsplus','-o','force,rw','/dev/vda',ROOT)
    for name,dev,dest in [('os','/dev/vdc',ROOT),('sysos','/dev/vdd',ROOT/'private/preboot/Cryptexes/OS'),('appos','/dev/vde',ROOT/'private/preboot/Cryptexes/App')]:
        mount,scratch=mount_firmware(name,dev,images[name])
        dest.mkdir(parents=True,exist_ok=True)
        print('COPYING '+name,flush=True)
        run('rsync','-aH','--numeric-ids','--info=progress2','--outbuf=L',
            str(mount/'root')+'/',str(dest)+'/',timeout=3600)
        run('umount',mount,timeout=60)
        if scratch:
            if scratch.parent!=ROOT or not scratch.name.startswith('.studio-firmware-'):
                raise RuntimeError('Refusing cleanup of an unexpected firmware staging path')
            scratch.unlink()
            print('STUDIO_FIRMWARE_STAGING_REMOVED '+name,flush=True)
    stage('Linking system and app cryptex files')
    linked=0;last_link=time.monotonic()
    for c in ('OS','App'):
        source=ROOT/'private/preboot/Cryptexes'/c
        for base,dirs,files in os.walk(source,followlinks=False):
            for name in files+list(d for d in dirs if (Path(base)/d).is_symlink()):
                src=Path(base)/name;dest=ROOT/src.relative_to(source)
                if dest.exists() or dest.is_symlink():continue
                dest.parent.mkdir(parents=True,exist_ok=True)
                if src.is_symlink():dest.symlink_to(os.readlink(src))
                else:os.link(src,dest)
                linked+=1
                if time.monotonic()-last_link>=5:
                    print('Linked '+str(linked)+' cryptex files',flush=True);last_link=time.monotonic()
    stage('Configuring iOS directories and root compatibility')
    db=ROOT/'private/var/db'
    for rel,mode in [('diagnostics',0o751),('uuidtext',0o755),('diagnostics/timesync',0o755)]:
        p=db/rel;p.mkdir(parents=True,exist_ok=True);os.chown(p,272,272);p.chmod(mode)
        marker=p/'.migrated';marker.touch();os.chown(marker,272,272);marker.chmod(0o644)
    p=ROOT/'private/var/keybags';p.mkdir(parents=True,exist_ok=True);p.chmod(0o700)
    keybag=p/'systembag.kb';keybag.write_bytes(plistlib.dumps({'KeyBagKeys':b'SWEET'}));keybag.chmod(0o600)
    run(sys.executable,'/tools/sweet-root-tweaks.py',ROOT)
    stage('Verifying MobileGestalt cache before compatibility patch')
    mg=module('Patch-IosSweet-MGCompat');cache=ROOT/mg.CACHE.lstrip('/')
    digest=sha(cache)
    if digest==mg.ORIGINAL_SHA256:
        with cache.open('r+b') as f:
            f.seek(mg.INSTRUCTION_OFFSET)
            if f.read(4)!=mg.ORIGINAL_INSTRUCTION:raise RuntimeError('Unexpected MobileGestalt instruction')
            f.seek(mg.INSTRUCTION_OFFSET);f.write(mg.PATCHED_INSTRUCTION)
    elif digest!=mg.PATCHED_SHA256:raise RuntimeError('Unsupported Apple cache: pinned compatibility patch refused')
    stage('Verifying the patched cache checksum')
    if sha(cache)!=mg.PATCHED_SHA256:raise RuntimeError('Private cache verification failed')
    print('PRIVATE_MG_COMPAT_VERIFIED',flush=True)

def seed(job):
    stage('Installing app-management and network services')
    path=ROOT/'System/Library/xpc/launchd.plist'
    launchd=plistlib.loads(path.read_bytes());jobs=launchd.get('LaunchDaemons')
    if not isinstance(jobs,dict) or len(jobs)<100:raise RuntimeError('Not a prepared iOS Sweet root')
    bridge={'Token':job['token'],'InstanceId':job['instanceId'],'BundleId':'com.iosnova','BundlePath':'/Applications/iOSNova.app'}
    for source,dest,mode in [('iossweet-agent','usr/local/libexec/iossweet-agent',0o755),('iossweet-net-seed','usr/local/libexec/iossweet-net-seed',0o755)]:
        src=Path('/job')/source
        if sha(src)!=job['hashes'][source]:raise RuntimeError('Helper SHA-256 mismatch')
        out=ROOT/dest;out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,out);out.chmod(mode)
    private=ROOT/'private/var/iossweet';private.mkdir(parents=True,exist_ok=True);private.chmod(0o700)
    config=private/'bridge.plist';config.write_bytes(plistlib.dumps(bridge,fmt=plistlib.FMT_BINARY));config.chmod(0o600)
    for label,program,keep in [('org.iossweet.development-agent','iossweet-agent',True),('org.iossweet.network-seed','iossweet-net-seed',False)]:
        entry={'Label':label,'ProgramArguments':['/usr/local/libexec/'+program],'RunAtLoad':True,'UserName':'root',
            'ProcessType':'Background','JetsamProperties':{'MemoryLimit':256},'StandardOutPath':'/private/var/iossweet/'+program+'.log',
            'StandardErrorPath':'/private/var/iossweet/'+program+'.log'}
        if keep:entry.update(KeepAlive=True,ThrottleInterval=15)
        key='/System/Library/LaunchDaemons/'+label+'.plist';jobs[key]=entry
        out=ROOT/key.lstrip('/');out.write_bytes(plistlib.dumps(entry));out.chmod(0o644)
    path.write_bytes(plistlib.dumps(launchd,fmt=plistlib.FMT_BINARY))
    print('STUDIO_AGENT_SEEDED',flush=True)

def main():
    job=json.loads(Path('/job/job.json').read_text())
    if job.get('schema')!=1 or job.get('mode') not in ('seed','full'):raise RuntimeError('Unsupported job')
    import re
    if not re.fullmatch('[0-9a-f]{64}',job.get('token','')):raise RuntimeError('Invalid capability')
    if job['mode']=='full':populate(job.get('firmware'))
    else:
        # Only the new private overlay is writable. Never repair the source disk.
        stage('Checking the private HFSX image before mounting')
        rc=subprocess.run(['/usr/sbin/fsck.hfsplus','-fy','/dev/vda'],timeout=600).returncode
        if rc not in (0,1):raise RuntimeError('Private HFSX check failed: '+str(rc))
        run('mount','-t','hfsplus','-o','force,rw','/dev/vda',ROOT)
    seed(job)
    stage('Flushing changes and unmounting the private disk')
    run('sync');run('umount',ROOT)
    if job['mode']=='full':
        stage('Final HFSX repair and consistency check')
        rc=subprocess.run(['/usr/sbin/fsck.hfsplus','-fy','/dev/vda'],timeout=600).returncode
        if rc not in (0,1):raise RuntimeError('Final HFSX repair failed')
    stage('Final read-only filesystem verification')
    run('/usr/sbin/fsck.hfsplus','-fn','/dev/vda',timeout=600)


def log_self_test():
    stage('Preparation logging self-test; no disks are opened')
    run('rsync','--version',timeout=10)
    for percent in (0,50,100):
        print('\r'+str(percent*1024)+' '+str(percent)+'% 1.00MB/s 0:00:01',end='',flush=True)
        time.sleep(.2)
    print('\nSTUDIO_DIAGNOSTIC_OUTPUT_VERIFIED',flush=True)


def transport_self_test():
    """Native CI uses ONLY a new 64-MiB target and synthetic non-Apple data."""
    if 'studio_transport_smoke=1' not in Path('/proc/cmdline').read_text().split():
        raise RuntimeError('Transport self-test requires its explicit kernel flag')
    job=json.loads(Path('/job/job.json').read_text())
    meta=job.get('fixture',{})
    if (job.get('mode')!='synthetic-transport-test' or
        Path('/sys/class/block/vda/size').read_text().strip()!='131072' or
        type(meta.get('size')) is not int or not 512<meta['size']<1024**2):
        raise RuntimeError('Refusing to format anything except the synthetic 64-MiB test target')
    with Path('/dev/vdc').open('rb') as f:
        if not f.read(32).startswith(b'STUDIO_SYNTHETIC_UDIF'):
            raise RuntimeError('This test accepts only its synthetic fixture; no Apple firmware')
    stage('Synthetic exact-length firmware transport; no Apple firmware or existing device')
    run('/usr/sbin/mkfs.hfsplus','-s','-v','StudioTest','/dev/vda',timeout=60)
    run('mount','-t','hfsplus','-o','force,rw','/dev/vda',ROOT,timeout=30)
    out=ROOT/'synthetic.dmg';copy_exact_firmware(Path('/dev/vdc'),out,meta)
    if out.stat().st_size!=meta['size']:raise RuntimeError('Synthetic image length changed')
    out.unlink();run('umount',ROOT,timeout=30)
    print('STUDIO_TRANSPORT_TEST_SUCCESS',flush=True)

if __name__=='__main__':
    try:
        if sys.argv[1:]==['--log-self-test']:log_self_test()
        elif sys.argv[1:]==['--transport-self-test']:transport_self_test()
        else:main()
    except Exception as e:print('STUDIO_PREPARER_ERROR '+str(e),flush=True);raise
