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

ROOT=Path('/target')

def run(*args):
    print('PREPARE_STEP '+str(args[0]),flush=True)
    subprocess.run(list(map(str,args)),check=True)

def module(name):
    spec=importlib.util.spec_from_file_location(name,Path('/tools')/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
    return h.hexdigest()

def populate():
    print('ASSEMBLING_PRIVATE_IOS_ROOT',flush=True)
    mounts=[]
    for name,dev in [('os','/dev/vdc'),('sysos','/dev/vdd'),('appos','/dev/vde')]:
        src=Path('/firmware')/(name+'.dmg');src.symlink_to(dev)
        mount=Path('/firmware')/name;mount.mkdir()
        run('/usr/local/bin/apfs-fuse','-o','allow_other',src,mount)
        if not (mount/'root').is_dir():raise RuntimeError('Apple APFS image lacks root directory: '+name)
        mounts.append(mount)
    run('/usr/sbin/mkfs.hfsplus','-s','-J','-v','iOSRoot','/dev/vda')
    run('mount','-t','hfsplus','-o','force,rw','/dev/vda',ROOT)
    for name,dest in [('os',ROOT),('sysos',ROOT/'private/preboot/Cryptexes/OS'),('appos',ROOT/'private/preboot/Cryptexes/App')]:
        dest.mkdir(parents=True,exist_ok=True)
        print('COPYING '+name,flush=True)
        run('rsync','-aH','--numeric-ids',str(Path('/firmware')/name/'root')+'/',str(dest)+'/')
    for c in ('OS','App'):
        source=ROOT/'private/preboot/Cryptexes'/c
        for base,dirs,files in os.walk(source,followlinks=False):
            for name in files+list(d for d in dirs if (Path(base)/d).is_symlink()):
                src=Path(base)/name;dest=ROOT/src.relative_to(source)
                if dest.exists() or dest.is_symlink():continue
                dest.parent.mkdir(parents=True,exist_ok=True)
                if src.is_symlink():dest.symlink_to(os.readlink(src))
                else:os.link(src,dest)
    db=ROOT/'private/var/db'
    for rel,mode in [('diagnostics',0o751),('uuidtext',0o755),('diagnostics/timesync',0o755)]:
        p=db/rel;p.mkdir(parents=True,exist_ok=True);os.chown(p,272,272);p.chmod(mode)
        marker=p/'.migrated';marker.touch();os.chown(marker,272,272);marker.chmod(0o644)
    p=ROOT/'private/var/keybags';p.mkdir(parents=True,exist_ok=True);p.chmod(0o700)
    keybag=p/'systembag.kb';keybag.write_bytes(plistlib.dumps({'KeyBagKeys':b'SWEET'}));keybag.chmod(0o600)
    run(sys.executable,'/tools/sweet-root-tweaks.py',ROOT)
    mg=module('Patch-IosSweet-MGCompat');cache=ROOT/mg.CACHE.lstrip('/')
    digest=sha(cache)
    if digest==mg.ORIGINAL_SHA256:
        with cache.open('r+b') as f:
            f.seek(mg.INSTRUCTION_OFFSET)
            if f.read(4)!=mg.ORIGINAL_INSTRUCTION:raise RuntimeError('Unexpected MobileGestalt instruction')
            f.seek(mg.INSTRUCTION_OFFSET);f.write(mg.PATCHED_INSTRUCTION)
    elif digest!=mg.PATCHED_SHA256:raise RuntimeError('Unsupported Apple cache: pinned compatibility patch refused')
    if sha(cache)!=mg.PATCHED_SHA256:raise RuntimeError('Private cache verification failed')
    print('PRIVATE_MG_COMPAT_VERIFIED',flush=True)

def seed(job):
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
    if job['mode']=='full':populate()
    else:
        # Only the new private overlay is writable. Never repair the source disk.
        rc=subprocess.run(['/usr/sbin/fsck.hfsplus','-fy','/dev/vda']).returncode
        if rc not in (0,1):raise RuntimeError('Private HFSX check failed: '+str(rc))
        run('mount','-t','hfsplus','-o','force,rw','/dev/vda',ROOT)
    seed(job)
    run('sync');run('umount',ROOT)
    if job['mode']=='full':
        rc=subprocess.run(['/usr/sbin/fsck.hfsplus','-fy','/dev/vda'],stdout=subprocess.DEVNULL).returncode
        if rc not in (0,1):raise RuntimeError('Final HFSX repair failed')
    run('/usr/sbin/fsck.hfsplus','-fn','/dev/vda')

if __name__=='__main__':
    try:main()
    except Exception as e:print('STUDIO_PREPARER_ERROR '+str(e),flush=True);raise
