"""Plan a native Windows launch; --run explicitly starts the guest paused."""
from pathlib import Path
import argparse
import ctypes
import json
import os
import plistlib
import re
import subprocess

REPO = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get('IOS_GPU_SOURCE_ROOT', REPO / '.studio/windows-gpu-sources')).resolve()
QEMU_DATA = ROOT / 'qemu-vphone-windows/pc-bios'
QEMU = Path(os.environ.get('IOS_GPU_QEMU', REPO / '.studio/windows-gpu-build/qemu-system-aarch64.exe'))


def bundle_file(bundle, name):
    path = (bundle / name).resolve()
    if not path.is_relative_to(bundle) or not path.is_file():
        raise ValueError(f'Missing or out-of-bundle file: {name}')
    if ',' in str(path):
        raise ValueError('Bundle paths containing commas are not supported')
    return path.as_posix()


def plan(bundle, memory='8G', cores=4, port=19488, headless=False, vusb_port=None, serial_log=None, restore_only=False, aux_override=None):
    bundle = Path(bundle).resolve(strict=True)
    if not (QEMU_DATA / 'efi-virtio.rom').is_file():
        raise ValueError(f'Missing QEMU network option ROM: {QEMU_DATA / "efi-virtio.rom"}')
    if not re.fullmatch(r'[1-9][0-9]*[MG]', memory):
        raise ValueError('Memory must be a positive integer followed by M or G')
    if not 1 <= cores <= 16 or not 1024 <= port <= 65535:
        raise ValueError('Invalid core count or QMP port')
    if vusb_port is not None and (not 1024 <= vusb_port <= 65535 or vusb_port == port):
        raise ValueError('VUSB port must be valid and distinct from QMP')
    serial_output = 'null'
    if serial_log:
        log = Path(serial_log).resolve()
        if log.exists() or not log.parent.is_dir() or ',' in str(log):
            raise ValueError('Serial log must be a new file in an existing directory without commas')
        serial_output = 'file:' + log.as_posix()
    config = plistlib.loads(Path(bundle_file(bundle, 'config.plist')).read_bytes())
    roms = config.get('romImages') or {}
    boot = bundle_file(bundle, roms.get('avpBooter') or 'AVPBooter.vresearch1.bin')
    sep = bundle_file(bundle, roms.get('avpSEPBooter') or 'AVPSEPBooter.vresearch1.bin')
    disk = bundle_file(bundle, 'Disk.img')
    nvram = bundle_file(bundle, 'nvram.bin')
    if aux_override is not None:
        override = Path(aux_override).resolve(strict=True)
        if not restore_only:
            raise ValueError('Aux override requires restore-only mode')
        if override == Path(nvram).resolve() or not override.is_file():
            raise ValueError('Aux override must be a separate regular file')
        if override.stat().st_size != 16384 + 32 * 1024**2:
            raise ValueError('Aux override must be exactly 16 KiB header plus 32 MiB')
        if ',' in str(override):
            raise ValueError('Aux override path cannot contain commas')
        nvram = str(override)
    if Path(nvram).stat().st_size <= 16384:
        raise ValueError('nvram.bin must include its 16 KiB aux-storage header')
    ecid = ''.join(Path(bundle_file(bundle, 'ecid')).read_text().split())
    if not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{1,16}', ecid):
        raise ValueError('ecid must contain at most 16 hexadecimal digits')
    ecid = hex(int(ecid, 16))
    resolution = (bundle / 'gfx-res').read_text().strip() if (bundle / 'gfx-res').exists() else '1290x2796'
    if not re.fullmatch(r'[1-9][0-9]{1,4}x[1-9][0-9]{1,4}', resolution):
        raise ValueError('Invalid gfx-res')
    machine = f'vresearch101,ecid={ecid},sep-rom={sep},gfx-device=apple-gfx-mmio,memory-backend=ram0,gfx-modes={resolution}@60'
    if (bundle / 'serial').exists():
        serial = (bundle / 'serial').read_text().strip()
        if not re.fullmatch(r'[A-Za-z0-9-]{1,64}', serial):
            raise ValueError('Invalid serial')
        machine += ',serial=' + serial
    args = [str(QEMU), '-L', str(QEMU_DATA), '-machine', machine, '-accel', 'tcg,tb-size=2048',
            '-smp', f'{cores},maxcpus={cores + 1}', '-m', memory,
            '-object', f'memory-backend-ram,id=ram0,size={memory},share=on',
            '-global', 'apple-gfx-mmio.process-isolation=on',
            '-global', 'apple-gfx-mmio.guest-page-shift=14',
            '-global', f'apple-gfx-mmio.resolution={resolution}', '-bios', boot]
    for spec in [f'file={nvram},if=pflash,format=raw,offset=16384,file.locking=off',
                 f'file={disk},if=pflash,format=raw,file.locking=off',
                 f'file={disk},if=none,id=root-pci,format=raw,file.locking=off',
                 f'file={nvram},if=none,id=aux-pci,format=raw,offset=16384,file.locking=off']:
        args += ['-drive', spec]
    if (bundle / 'SEPStorage').exists():
        args += ['-drive', f'file={bundle_file(bundle, "SEPStorage")},if=none,id=sep-storage,format=raw,file.locking=off']
    if vusb_port is not None:
        args += ['-chardev', f'socket,id=vusb,host=127.0.0.1,port={vusb_port},server=on,wait=off,nodelay=on',
                 '-global', 'vresearch-vusb.chardev=vusb']
    args += ['-display', 'none', '-serial', serial_output, '-monitor', 'none',
             '-qmp', f'tcp:127.0.0.1:{port},server=on,wait=off,nodelay=on',
             '-nic', 'user,model=virtio-net-pci', '-S']
    if restore_only:
        index = args.index('-machine') + 1
        args[index] = args[index].replace('gfx-device=apple-gfx-mmio', 'gfx-device=none')
        for value in ['apple-gfx-mmio.process-isolation=on', 'apple-gfx-mmio.guest-page-shift=14',
                      f'apple-gfx-mmio.resolution={resolution}']:
            index = args.index(value)
            del args[index - 1:index + 1]
    env = {'PATH': str(ROOT / 'reims-win-dist/lib') + ';' + os.environ.get('IOS_GPU_UCRT_BIN', str(REPO / '.studio/toolchains/msys64/ucrt64/bin')) + ';' + os.environ['PATH'],
           'REIMS_VGPU_WINDOW': '0' if headless else '1',
           'REIMS_VGPU_WINDOW_TITLE': 'Native Windows iPhone GPU experiment',
           'VPHONE_TARGET_PAGE_BITS': '14', 'VPHONE_TLB_RANGE_PAGES': '1',
           'VPHONE_XPAGE_LINKS': '1', 'VPHONE_RET_PREFETCH': '2',
           'QEMU_TLB_UNSYNCED': '2', 'VPHONE_XHCI_NONREMOVABLE': '0x1fe'}
    # Normal interaction should not synchronously trace every pointer/report and
    # FIFO command. Explicit diagnostics remain available when investigating.
    env.update(REIMS_EXPERIMENT_ASTC_CPU='1', REIMS_EXPERIMENT_ASTC_NIL='0', REIMS_VGPU_FORWARD_FOCUS_CLICK='1',
               REIMS_VGPU_LOG='warn', REIMS_VGPU_INPUT_TRACE='0',
               VPHONE_TOUCH_TRACE='0', REIMS_VGPU_STATS='0')
    return {'args': args, 'environment': env, 'paused': True,
            'limitations': ['Experimental GPU setup observed; stable usable iPhone acceptance incomplete',
                             'No Windows vsock/vphoned or upstream toolbar integration',
                             'No GPU snapshot/migration support',
                             'Writable bundle must be an isolated working copy; no automatic overlays',
                             'Upstream Metal translation limitations and linker warnings remain']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle')
    parser.add_argument('--memory', default='8G')
    parser.add_argument('--cores', type=int, default=4)
    parser.add_argument('--qmp-port', type=int, default=19488)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--restore-only', action='store_true', help='Disable the GPU device for firmware restoration; no iOS display')
    parser.add_argument('--vusb-port', type=int, help='Expose VUSB on a distinct Windows loopback TCP port')
    parser.add_argument('--serial-log', help='New serial log file; created only by QEMU with --run')
    parser.add_argument('--aux-override', help='Separate temporary auxiliary image for SSH DFU boot; restore-only required')
    parser.add_argument('--run', action='store_true', help='Open the isolated bundle writable and start paused; QMP cont is separate')
    parser.add_argument('--diagnostics', action='store_true', help='Enable input, FIFO, GPU timing and per-second frame diagnostics')
    parser.add_argument('--idle-input-workaround', action='store_true', help='Experimental Windows touch profile: no system-keyboard grab and a 16ms main-loop wait cap')
    options = parser.parse_args()
    result = plan(options.bundle, options.memory, options.cores, options.qmp_port, options.headless,
                  options.vusb_port, options.serial_log, options.restore_only, options.aux_override)
    if options.diagnostics:
        result['environment'].update(REIMS_VGPU_INPUT_TRACE='1', VPHONE_TOUCH_TRACE='1', REIMS_VGPU_STATS='1',
            REIMS_VGPU_LOG='warn,reims_vgpu_vulkan::gpu::timing=debug,reims_vgpu_core::fifo::commands=debug,reims_vgpu_vulkan::os::windows::vm=debug')
    if options.idle_input_workaround:
        result['environment'].update(REIMS_VGPU_WINDOW_KEYBOARD_GRAB='0', VPHONE_WIN32_POLL_MAX_MS='16')
    print(json.dumps(result, indent=2))
    if options.run:
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in
                ['total', 'available', 'total_page', 'available_page',
                 'total_virtual', 'available_virtual', 'extended']]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise RuntimeError('Cannot verify available Windows memory')
        required = int(options.memory[:-1]) * (1024 ** (2 if options.memory[-1] == 'M' else 3))
        if status.available < required + 4 * 1024 ** 3:
            raise RuntimeError('Insufficient available RAM: guest memory plus 4 GiB headroom for cache and renderer required')
        env = os.environ.copy()
        env.update(result['environment'])
        return subprocess.call(result['args'], env=env)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
