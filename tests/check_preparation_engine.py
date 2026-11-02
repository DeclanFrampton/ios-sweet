"""Boot the exact public setup engine without a disk, firmware, network or iPhone.

This catches missing ROMs that `qemu --version` alone does not detect.
"""
import argparse
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from bundles import sha256
import preparation_initrd
from preparation_log import PreparationLog, monitor, read_latest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();assets=args.assets.resolve();home=args.output.resolve();home.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((assets/'manifest.json').read_text())
    for name in ('prepare-kernel','prepare-initrd.gz'):
        if sha256(assets/name)!=manifest[name]:raise RuntimeError('Setup asset is not verified: '+name)
    for name in ('bios-256k.bin','linuxboot_dma.bin','multiboot_dma.bin','pvh.bin'):
        if not (assets/'qemu/share'/name).is_file():raise RuntimeError('Setup boot ROM is missing: '+name)
    overlay=preparation_initrd.build(assets/'prepare-initrd.gz',ROOT,home/('log-test-'+uuid.uuid4().hex+'.gz'))
    command=[str(assets/'qemu/qemu-system-x86_64.exe'),'-machine','q35','-accel','tcg,thread=multi',
        '-smp','2','-m','512','-display','none','-monitor','none','-serial','stdio','-no-reboot','-nic','none',
        '-kernel',str(assets/'prepare-kernel'),'-initrd',str(overlay),
        '-append','console=ttyS0 rdinit=/init panic=-1 loglevel=6 studio_log_smoke=1']
    print('BOOT_ACCEPTANCE: no disks attached; no Apple firmware; no network',flush=True)
    try:
        with PreparationLog(home,'diagnostic',print) as log:
            monitor(command,log,'Booting the diskless preparation-engine acceptance test',timeout=240,
                success_marker='STUDIO_LOG_SMOKE_SUCCESS')
            text=log.path.read_text(encoding='utf-8')
            for expected in ('STUDIO_LOGGING_VERSION 2','STUDIO_DIAGNOSTIC_OUTPUT_VERIFIED'):
                if expected not in text:raise RuntimeError('Source logging overlay was not verified: '+expected)
        summary=read_latest(home)
        print('PREPARATION_ENGINE_BOOT_PASS '+json.dumps({k:summary.get(k) for k in
            ('status','stage','elapsedSeconds','exitCode','cpuSeconds','copyProgress')}),flush=True)
    finally:overlay.unlink(missing_ok=True)


if __name__=='__main__':main()
