"""Run the checked-out Studio source using a private embedded CPython.

Python's embedded distribution deliberately omits the script directory from
sys.path. This explicit entry point makes only our desktop/tools modules
available, including child tooling; it never uses an installed system Python.
"""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TOOLS = ('iossweet-native-windows.py', 'mkadt.py', 'mkpayload.py')


def configure():
    sys.path[:0] = [str(ROOT / 'desktop'), str(ROOT / 'tools')]
    os.environ['IOS_SWEET_SOURCE_ENTRY'] = str(Path(__file__).resolve())
    # Importing/running source must not write outside its source/cache tree.
    sys.dont_write_bytecode = True


def check_runtime():
    if os.name != 'nt':
        raise RuntimeError('This launcher currently supports Windows x64.')
    import struct
    if struct.calcsize('P') != 8:
        raise RuntimeError('A 64-bit Python runtime is required.')
    import webview
    import clr
    import lief
    from PIL import Image
    import bundles
    import runtime_setup
    import studio
    import adt
    import product_tree
    clr.AddReference('System.Windows.Forms')
    asset, qemu = runtime_setup.asset_paths(ROOT)
    signer = asset / 'rcodesign.exe'
    if not signer.is_file():
        raise RuntimeError('The local signer is missing from the runtime pack.')
    for executable in (qemu/'qemu-system-aarch64.exe', qemu/'qemu-system-x86_64.exe', qemu/'qemu-img.exe', signer):
        result = subprocess.run([str(executable), '--version'], capture_output=True,
                                timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError('Runtime component cannot start: ' + executable.name)
    # Version banners cannot prove the new decoder actually handles binary
    # pipes on a fresh Windows PC; round-trip public synthetic bytes only.
    sample=b'Studio native decoder preflight\0\xff'*128
    compressed=subprocess.run([str(asset/'lzfse.exe'),'-encode'],input=sample,
        capture_output=True,check=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW).stdout
    decoded=subprocess.run([str(asset/'lzfse.exe'),'-decode'],input=compressed,
        capture_output=True,check=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW).stdout
    if decoded!=sample:raise RuntimeError('Native firmware decoder failed its binary round-trip check.')
    for name in ('studio.py','bundles.py','runtime_setup.py'):
        compile((ROOT/'desktop'/name).read_text(encoding='utf-8'), name, 'exec')
    print(json.dumps({'status':'ready', 'python':sys.version.split()[0],
                      'pythonExecutable':sys.executable, 'sourceRoot':str(ROOT),
                      'assetRoot':str(asset), 'codeRunsFromClone':True}))


def main():
    configure()
    if sys.argv[1:2] == ['--check-runtime']:
        check_runtime()
        return
    if sys.argv[1:2] == ['--test-source']:
        import unittest
        suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'), pattern='test_*.py')
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if sys.argv[1:2] == ['--tool']:
        if len(sys.argv)<3 or sys.argv[2] not in ALLOWED_TOOLS:
            raise SystemExit('Unsupported source tool. No command was executed.')
        target = ROOT/'tools'/sys.argv[2]
        sys.argv = [str(target), *sys.argv[3:]]
    else:
        if sys.argv[1:] and sys.argv[1] not in ('--ipa', '--self-test'):
            raise SystemExit('Unknown Studio argument.')
        target = ROOT/'desktop/studio.py'
        sys.argv = [str(target), *sys.argv[1:]]
    runpy.run_path(str(target), run_name='__main__')


if __name__ == '__main__':
    main()
