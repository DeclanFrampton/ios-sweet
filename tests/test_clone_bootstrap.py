"""Regression checks for clone -> start.cmd without a system Python/SDK."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


class CloneBootstrapTests(unittest.TestCase):
    def test_source_wrapper_has_one_command_and_no_app_installer(self):
        text=(ROOT/'start.cmd').read_text()
        self.assertIn('tools\\Start-Studio.ps1',text)
        self.assertIn('-NoProfile',text)
        self.assertNotIn('Setup.exe',text)
        self.assertNotIn('pip install',text)
        ps=(ROOT/'tools/Start-Studio.ps1').read_text()
        self.assertIn('desktop\\source_entry.py',ps)
        self.assertNotIn('Set-ExecutionPolicy',ps)
        self.assertNotIn('-Verb RunAs',ps)
        self.assertNotIn('SetEnvironmentVariable',ps)

    def test_runtime_lock_is_pinned_public_and_immutable(self):
        lock=json.loads((ROOT/'desktop/runtime-lock.json').read_text())
        self.assertEqual(lock['schema'],1)
        self.assertEqual(lock['platform'],'windows-x64')
        self.assertTrue(lock['archiveUrl'].startswith('https://github.com/danhol86/ios-sweet/releases/download/'))
        self.assertNotIn('/latest/',lock['archiveUrl'])
        for key in ('archiveSha256','inventorySha256'):
            self.assertRegex(lock[key],r'^[0-9a-f]{64}$')
        self.assertGreater(lock['archiveBytes'],1024**2)

    def test_source_entry_rejects_arbitrary_tools(self):
        result=subprocess.run([sys.executable,str(ROOT/'desktop/source_entry.py'),'--tool','arbitrary-command.py'],
                              capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Unsupported source tool',result.stderr)

    def test_vendor_unpack_rejects_traversal(self):
        pack=load('test_runtime_pack',ROOT/'desktop/build_runtime_pack.py')
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'bad.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape.txt',b'bad')
            with self.assertRaisesRegex(ValueError,'Unsafe'):
                pack.unpack(archive,Path(folder)/'destination')
            self.assertFalse((Path(folder)/'escape.txt').exists())

    def test_source_tools_use_embedded_entrypoint(self):
        source=(ROOT/'desktop/studio.py').read_text()
        native=(ROOT/'tools/iossweet-native-windows.py').read_text()
        for text in (source,native):self.assertIn("os.environ['IOS_SWEET_SOURCE_ENTRY']",text)
        runner=load('test_source_entry',ROOT/'desktop/source_entry.py')
        self.assertEqual(set(runner.ALLOWED_TOOLS),{'mkadt.py','mkpayload.py','iossweet-native-windows.py'})

    def test_dependency_lock_is_complete_not_build_environment(self):
        text=(ROOT/'desktop/runtime-requirements.txt').read_text()
        self.assertIn('pythonnet==3.2.1',text)
        self.assertIn('pywebview==6.2.1',text)
        self.assertNotIn('pyinstaller==',text.lower())
        for line in text.splitlines():
            if line and not line.startswith('#'):
                self.assertRegex(line,r'^[A-Za-z0-9_]+==[0-9.]+$')

    def test_cache_and_private_devices_are_ignored(self):
        self.assertIn('.studio/',(ROOT/'.gitignore').read_text())
        bootstrap=(ROOT/'tools/Start-Studio.ps1').read_text()
        self.assertIn("Join-Path $cache 'data'",bootstrap)
        self.assertIn("Test-StudioRuntime",bootstrap)
        self.assertIn('PrepareOnly',bootstrap)

    def test_bootstrap_waits_for_native_window_not_just_http(self):
        bootstrap=(ROOT/'tools/Start-Studio.ps1').read_text()
        app=(ROOT/'desktop/studio.py').read_text()
        self.assertIn('$session.uiReady -eq $true',bootstrap)
        self.assertIn('$process.MainWindowHandle -ne [IntPtr]::Zero',bootstrap)
        self.assertIn('-FilePath $guiPython',bootstrap)
        self.assertIn('-WindowStyle Normal -RedirectStandardOutput',bootstrap)
        self.assertIn('app.window.events.loaded+=window_loaded',app)
        self.assertIn("'uiReady':False",app)
        self.assertIn("'uiReady':True",app)

    def test_optional_data_location_is_remembered_only_in_clone(self):
        bootstrap=(ROOT/'tools/Start-Studio.ps1').read_text()
        self.assertIn("Join-Path $cache 'settings.json'",bootstrap)
        self.assertIn('Assert-StudioPath $saved.dataDirectory',bootstrap)
        self.assertNotIn('Set-ItemProperty',bootstrap)

    @unittest.skipUnless(os.name=='nt','PowerShell bootstrap requires Windows')
    def test_powershell_archive_integrity_and_boundary_checks(self):
        result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
                               str(ROOT/'tests/check_studio_bootstrap.ps1')],
                              capture_output=True,text=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        self.assertIn('BOOTSTRAP_BOUNDARY_TESTS_PASS',result.stdout)


if __name__=='__main__':unittest.main()
