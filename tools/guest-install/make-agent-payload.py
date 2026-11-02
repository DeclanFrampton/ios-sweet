#!/usr/bin/env python3
"""Build a private test payload, preserving all original launchd jobs.

The work directory must contain the extracted original launchd plist,
locally compiled agent, and a randomly generated private bridge config.
This only creates a tar file. It does not mount/write any guest disk.
"""
import argparse
import io
from pathlib import Path
import plistlib
import tarfile


def create(work):
    work=Path(work).resolve()
    launchd=plistlib.loads((work/'launchd.original.plist').read_bytes())
    config=plistlib.loads((work/'payload/private/var/iossweet/bridge.plist').read_bytes())
    if config.get('BundleId') != 'com.iosnova' or config.get('BundlePath') != '/Applications/iOSNova.app':
        raise ValueError('This acceptance payload permits only the supplied iOSNova test app')
    label='org.iossweet.development-agent'
    key='/System/Library/LaunchDaemons/'+label+'.plist'
    if key in launchd['LaunchDaemons']:
        raise ValueError('Use an original launchd configuration, not an already patched payload')
    job={'Label':label,'ProgramArguments':['/usr/local/libexec/iossweet-agent'],
         'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':15,'UserName':'root',
         'ProcessType':'Background','JetsamProperties':{'MemoryLimit':256},
         'StandardOutPath':'/private/var/iossweet/agent.log',
         'StandardErrorPath':'/private/var/iossweet/agent.log'}
    launchd['LaunchDaemons'][key]=job
    files={
        'System/Library/xpc/launchd.plist':(plistlib.dumps(launchd,fmt=plistlib.FMT_BINARY),0o644),
        key.lstrip('/'):(plistlib.dumps(job,fmt=plistlib.FMT_XML),0o644),
        'usr/local/libexec/iossweet-agent':((work/'iossweet-agent').read_bytes(),0o755),
        'private/var/iossweet/bridge.plist':(plistlib.dumps(config,fmt=plistlib.FMT_BINARY),0o600),
    }
    target=work/'agent-payload.tar'
    with tarfile.open(target,'w') as archive:
        directories=set()
        for name in files:
            p=Path(name).parent
            while str(p)!='.':directories.add(p.as_posix());p=p.parent
        for name in sorted(directories,key=lambda p:len(p.split('/'))):
            item=tarfile.TarInfo(name);item.type=tarfile.DIRTYPE
            item.mode=0o700 if name=='private/var/iossweet' else 0o755
            item.uid=item.gid=0;archive.addfile(item)
        for name,(data,mode) in files.items():
            item=tarfile.TarInfo(name);item.size=len(data);item.mode=mode
            item.uid=item.gid=0;archive.addfile(item,io.BytesIO(data))
    return len(files)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('private_work_directory',type=Path)
    args=parser.parse_args()
    print('PRIVATE_AGENT_PAYLOAD_FILES',create(args.private_work_directory))
