"""Native Windows preparation-engine test with synthetic data, not Apple firmware.

Unlike the diskless boot smoke, this checks real VirtIO/FAT job transport,
sector-rounded source media, exact DMG file length, SHA-256 and HFSX writes.
Every writable path is newly created under the supplied test output folder.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
import preparation_initrd
from preparation_log import PreparationLog,monitor,read_latest,HIDDEN
from bundles import sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();assets=args.assets.resolve()
    home=args.output.resolve()/('synthetic-'+uuid.uuid4().hex);home.mkdir(parents=True)
    manifest=json.loads((assets/'manifest.json').read_text())
    for name in ('prepare-kernel','prepare-initrd.gz'):
        if sha256(assets/name)!=manifest[name]:raise RuntimeError('Changed test dependency: '+name)
    job=home/'job';job.mkdir()
    data=b'STUDIO_SYNTHETIC_UDIF'+b'non-Apple fixture '*67+b'koly'+b'\0'*508
    assert len(data)%512
    source=home/'source.dmg';source.write_bytes(data)
    (job/'job.json').write_text(json.dumps({'mode':'synthetic-transport-test',
        'fixture':{'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}}))
    boot=preparation_initrd.build(assets/'prepare-initrd.gz',ROOT,home/'test-boot.gz')
    qemu=assets/'qemu';target=home/'test-target.raw'
    subprocess.run([str(qemu/'qemu-img.exe'),'create','-f','raw',str(target),'64M'],
        check=True,capture_output=True,creationflags=HIDDEN)
    def file(path):
        text=str(path).replace('\\','/')
        if ',' in text:raise ValueError('Test path must not contain commas')
        return text
    cmd=[str(qemu/'qemu-system-x86_64.exe'),'-machine','q35','-accel','tcg,thread=multi',
        '-smp','2','-m','512','-display','none','-monitor','none','-serial','stdio','-no-reboot','-nic','none',
        '-kernel',str(assets/'prepare-kernel'),'-initrd',str(boot),
        '-append','console=ttyS0 rdinit=/init panic=-1 loglevel=6 studio_transport_smoke=1',
        '-drive',f'file={file(target)},format=raw,if=virtio',
        '-drive',f'file=fat:ro:{file(job)},format=raw,if=virtio,readonly=on',
        '-drive',f'file={file(source)},format=raw,if=virtio,readonly=on']
    print('TRANSPORT_ACCEPTANCE: new 64-MiB test target; synthetic data; no network; no Apple firmware',flush=True)
    try:
        with PreparationLog(home,'synthetic-transport',print) as log:
            monitor(cmd,log,'Testing exact-length firmware transport',timeout=240,success_marker='STUDIO_PREPARER_SUCCESS')
            text=log.path.read_text(encoding='utf-8')
            for marker in ('STUDIO_TRANSPORT_TEST_SUCCESS','STUDIO_FIRMWARE_FILE_VERIFIED'):
                if marker not in text:raise RuntimeError('Real firmware-transport test did not reach '+marker)
            if source.read_bytes()!=data:raise RuntimeError('Read-only synthetic source was changed')
        print('PREPARATION_TRANSPORT_PASS '+json.dumps({'elapsedSeconds':read_latest(home)['elapsedSeconds'],
            'exactBytes':len(data),'sourceUnchanged':True}),flush=True)
    finally:
        # Exact fresh test files only; keep logs for CI artifacts.
        for p in (boot,target):p.unlink(missing_ok=True)


if __name__=='__main__':main()
