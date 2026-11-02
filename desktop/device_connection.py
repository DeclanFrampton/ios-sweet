"""Locate a running Studio device without scanning drives or changing a VM.

Discovery is only a hint. A reconnect rechecks the live PID, executable,
recorded QEMU command, exact overlay, kernel hash and authenticated guest ID.
Never stop an unrelated emulator or treat a stale state file as a live device.
"""
from __future__ import annotations
import ctypes
import json
import os
from pathlib import Path
import subprocess


def live_process_image(api, handle):
    """An exited process handle can briefly outlive its executable pathname.

    Treat a confirmed exit as stopped, not as an identity-check failure.
    Still fail closed if a running process's path cannot be verified.
    Caller owns/always closes the handle and configures the Windows API types.
    """
    from ctypes import wintypes
    def running():
        code=wintypes.DWORD()
        if not api.GetExitCodeProcess(handle,ctypes.byref(code)):
            raise RuntimeError('Cannot verify QEMU process exit state.')
        return code.value==259  # STILL_ACTIVE
    if not running():return None
    size=wintypes.DWORD(32768);buffer=ctypes.create_unicode_buffer(size.value)
    if not api.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):
        if not running():return None
        raise RuntimeError('Cannot verify running QEMU process image.')
    if not running():return None
    return buffer.value


def read_json(path: Path, limit=256*1024):
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Missing or oversized Studio metadata: '+path.name)
    return json.loads(path.read_text(encoding='utf-8-sig'))


def windows_arguments(command: str):
    if os.name != 'nt':raise RuntimeError('Windows process discovery is unavailable.')
    shell=ctypes.windll.shell32;kernel=ctypes.windll.kernel32
    shell.CommandLineToArgvW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype=ctypes.POINTER(ctypes.c_wchar_p)
    kernel.LocalFree.argtypes=[ctypes.c_void_p]
    argc=ctypes.c_int()
    argv=shell.CommandLineToArgvW(command,ctypes.byref(argc))
    if not argv:raise ValueError('Cannot parse QEMU command line.')
    try:return [argv[i] for i in range(argc.value)]
    finally:kernel.LocalFree(argv)


def processes():
    if os.name != 'nt':return []
    powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    script="[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); @(" \
        "Get-CimInstance Win32_Process -Filter \"Name='qemu-system-aarch64.exe'\" | " \
        "Select-Object ProcessId,ExecutablePath,CommandLine) | ConvertTo-Json -Compress"
    result=subprocess.run([str(powershell),'-NoLogo','-NoProfile','-NonInteractive','-Command',script],
        capture_output=True,text=True,encoding='utf-8',timeout=12,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError('Unable to check existing emulator processes; no device was changed.')
    value=json.loads(result.stdout.lstrip('\ufeff') or '[]')
    if isinstance(value,dict):value=[value]
    if not isinstance(value,list):raise ValueError('Unexpected process metadata.')
    return value


def option(arguments, name):
    values=[arguments[i+1] for i in range(len(arguments)-1) if arguments[i]==name]
    if len(values)!=1:raise ValueError('Expected exactly one QEMU '+name+' option.')
    return values[0]


def overlay_path(arguments):
    values=[]
    for i,arg in enumerate(arguments[:-1]):
        if arg!='-drive':continue
        fields=dict(piece.split('=',1) for piece in arguments[i+1].split(',') if '=' in piece)
        if fields.get('id')=='iosroot' and fields.get('if')=='none' and fields.get('format')=='qcow2':
            values.append(fields.get('file',''))
    if len(values)!=1 or not values[0]:raise ValueError('No unique iOS Sweet overlay in QEMU command.')
    p=Path(values[0])
    if not p.is_absolute():raise ValueError('Device overlay is not an absolute path.')
    return p.resolve(strict=True)


def validate_config(config, state, arguments, executable, pid):
    if not isinstance(config,dict) or config.get('schema')!=2:
        raise ValueError('Not a Studio device configuration.')
    if type(pid) is not int or state.get('qemu_pid')!=pid:
        raise ValueError('Saved device state does not match the live QEMU PID.')
    paths={}
    for name in ('disk','overlay','kernel','bridgeConfig','state','qemu'):
        value=config.get(name)
        if not isinstance(value,str) or not Path(value).is_absolute():
            raise ValueError('Device metadata has an invalid '+name+' path.')
        paths[name]=Path(value).resolve(strict=True)
        if name not in ('state','qemu') and not paths[name].is_file():
            raise ValueError('Required device file is missing: '+name)
    if not Path(executable).samefile(paths['qemu']/'qemu-system-aarch64.exe'):
        raise ValueError('Running executable does not match the saved device.')
    if overlay_path(arguments)!=paths['overlay']:
        raise ValueError('The running guest uses a different overlay.')
    serial=option(arguments,'-serial')
    if not serial.startswith('file:'):raise ValueError('Expected a local Studio serial log.')
    run=Path(serial[5:]).resolve().parent
    if Path(state.get('run','')).resolve()!=run or run.parent!=paths['state']:
        raise ValueError('Running guest does not match its state directory.')
    # The native controller stores options only, not argv[0]. The live
    # executable was independently checked above before comparing options.
    options=arguments[1:] if arguments and not arguments[0].startswith('-') else arguments
    if read_json(run/'command.json')!=options:
        raise ValueError('Saved command differs from the running guest command.')
    for name,field in (('viewerPort','viewer_port'),('qmpPort','qmp_port')):
        port=config.get(name)
        if type(port) is not int or not 1024<=port<=65535 or state.get(field)!=port:
            raise ValueError('Device port metadata does not match the live guest.')
    if option(arguments,'-qmp')!=f'tcp:127.0.0.1:{config["qmpPort"]},server=on,wait=off':
        raise ValueError('Guest monitor is not the expected loopback endpoint.')
    if state.get('kernel_sha256')!=config.get('kernelSha256'):
        raise ValueError('Live kernel identity does not match the device configuration.')
    bridge=read_json(paths['bridgeConfig'])
    import re
    if not re.fullmatch('[0-9a-f]{64}',str(bridge.get('Token',''))) or not config.get('instanceId') or bridge.get('InstanceId')!=config['instanceId']:
        raise ValueError('Private bridge identity is missing or does not match.')
    return config


def candidate(process, arguments):
    serial=option(arguments,'-serial')
    if not serial.startswith('file:'):raise ValueError('Not a Studio serial endpoint.')
    run=Path(serial[5:]).resolve().parent
    state=read_json(run.parent/'active-native.json')
    overlay=overlay_path(arguments)
    # Known Studio layout only: <home>/devices/<instance>/ios.qcow2, with
    # <home>/device.json. Also accept a device-local manifest for future exports.
    roots=(overlay.parent,overlay.parent.parent,overlay.parent.parent.parent)
    for root in roots:
        path=root/'device.json'
        if not path.is_file():continue
        try:
            config=validate_config(read_json(path),state,arguments,
                process.get('ExecutablePath',''),process.get('ProcessId'))
            return {'config':config,'source':str(path),'pid':process['ProcessId']}
        except (ValueError,OSError,KeyError,TypeError):continue
    raise ValueError('The running emulator has no matching Studio device configuration.')


def discover():
    result={'running':False,'canConnect':False,'message':'','candidate':None}
    try:
        live=processes()
        if not live:return result
        result['running']=True
        if len(live)!=1:
            result['message']='Several emulators are running. Close them from their original applications before selecting a device.'
            return result
        p=live[0]
        found=candidate(p,windows_arguments(p.get('CommandLine','')))
        result.update(canConnect=True,candidate=found,
            message='Your iPhone is already running in another Studio data folder. Connect to keep using its installed apps.')
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
        result['message']='Another emulator could not be verified. It has been left untouched; use its original Studio window.'
    return result
