"""Compare preparation accelerators using disposable, synthetic HFSX disks."""
import pathlib
import subprocess
import sys
import tempfile
import time

repo = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo / 'desktop'))
import preparation_initrd

asset = repo / '.studio/runtime/studio-runtime-v0.2.0-r3/assets'
qemu = asset / 'qemu/qemu-system-x86_64.exe'
img = asset / 'qemu/qemu-img.exe'

with tempfile.TemporaryDirectory(prefix='iossweet-prep-fixture-') as directory:
    root = pathlib.Path(directory)
    app = root / 'desktop/appliance'
    app.mkdir(parents=True)
    (app / 'init').write_text('''#!/bin/sh
export PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mkdir -p /tmp /target
mount -t tmpfs tmpfs /tmp
for m in virtio_pci virtio_blk hfsplus nls_utf8; do modprobe "$m"; done
python3 -u /tools/prepare.py
poweroff -f
''', encoding='utf-8')
    (app / 'prepare.py').write_text('''import pathlib, subprocess, hashlib, time
s=pathlib.Path('/tmp/source'); s.mkdir()
for i in range(1200):
 p=s/str(i//100)/str(i); p.parent.mkdir(exist_ok=True); p.write_bytes(bytes([i%251])*8192)
subprocess.run(['/usr/sbin/mkfs.hfsplus','-s','-J','-v','fixture','/dev/vda'],check=True)
subprocess.run(['mount','-t','hfsplus','-o','force,rw','/dev/vda','/target'],check=True)
t=time.monotonic(); subprocess.run(['rsync','-aH','--numeric-ids',str(s)+'/', '/target/'],check=True); print('COPY_SECONDS',round(time.monotonic()-t,3),flush=True)
for p in s.rglob('*'):
 if p.is_file() and hashlib.sha256(p.read_bytes()).digest()!=hashlib.sha256((pathlib.Path('/target')/p.relative_to(s)).read_bytes()).digest(): raise Exception('hash mismatch')
subprocess.run(['sync'],check=True); subprocess.run(['umount','/target'],check=True)
r=subprocess.run(['/usr/sbin/fsck.hfsplus','-fn','/dev/vda']); print('FSCK_RC',r.returncode,flush=True)
if r.returncode!=0: raise Exception('fsck failed')
print('FIXTURE_PASS',flush=True)
''', encoding='utf-8')
    boot = preparation_initrd.build(asset / 'prepare-initrd.gz', root, root / 'initrd.gz')
    for accel in ('whpx', 'tcg,thread=multi'):
        disk = root / ('disk-' + accel.split(',')[0] + '.raw')
        subprocess.run([str(img), 'create', '-f', 'raw', str(disk), '256M'], check=True, capture_output=True)
        cmd = [str(qemu), '-L', str(asset/'qemu/share'), '-machine', 'q35', '-accel', accel,
               '-smp', '2', '-m', '512', '-display', 'none', '-monitor', 'none', '-serial', 'stdio',
               '-no-reboot', '-nic', 'none', '-kernel', str(asset/'prepare-kernel'), '-initrd', str(boot),
               '-append', 'console=ttyS0 rdinit=/init panic=-1 loglevel=4',
               '-drive', f'file={disk.as_posix()},format=raw,if=virtio,cache=writeback']
        started = time.perf_counter()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        print(accel, 'wall_seconds', round(time.perf_counter()-started, 2), 'exit', result.returncode)
        print('\n'.join(line for line in result.stdout.splitlines() if 'COPY_SECONDS' in line or 'FSCK_RC' in line or 'FIXTURE_PASS' in line))
        if result.returncode or 'FIXTURE_PASS' not in result.stdout:
            raise RuntimeError('Fixture failed: ' + result.stdout[-3000:] + result.stderr[-1000:])
