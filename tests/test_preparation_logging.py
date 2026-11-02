"""Setup diagnostics: real subprocesses, bounded output, failure and privacy."""
import gzip
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
import preparation_log as logs
import preparation_initrd as initrd


class PreparationLogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.events=[];self.log=logs.PreparationLog(self.home,'test',self.events.append)
    def tearDown(self):self.temp.cleanup()
    def command(self,code):return [sys.executable,'-u','-c',code]
    def run_monitor(self,code,**kwargs):
        return logs.monitor(self.command(code),self.log,'Test setup step',heartbeat=.1,quiet_after=.15,**kwargs)

    def test_carriage_return_progress_and_named_stages(self):
        self.run_monitor("print('STUDIO_STAGE Copying the system');print('PREPARE_STEP rsync');print(' 1,024 50% 1.00MB/s\\r2,048 100% 2.00MB/s\\rDONE',end='')",success_marker='DONE',timeout=5)
        self.assertEqual(self.log.state['stage'],'Copying the system')
        self.assertEqual(self.log.state['copyProgress']['bytes'],2048)
        self.assertEqual(self.log.state['copyProgress']['percent'],100)
        self.assertEqual(self.log.state['exitCode'],0)

    def test_quiet_process_heartbeat_without_newline(self):
        self.run_monitor("import sys,time;sys.stdout.write('mounting without a newline');sys.stdout.flush();time.sleep(.5);print('\\nDONE')",success_marker='DONE',timeout=5)
        text=self.log.path.read_text()
        self.assertIn('Heartbeat:',text);self.assertIn('without a newline',text)
        self.assertIn('progress is not confirmed',text)

    def test_incremental_copy_discovery_is_not_presented_as_overall_completion(self):
        self.log.consume('6,452,584,469 99% 8.58MB/s 0:11:57 (xfr#143143, ir-chk=1040/262888)')
        copy=self.log.state['copyProgress']
        self.assertEqual(copy['transferredFiles'],143143)
        self.assertEqual(copy['discoveredEntries'],262888)
        self.assertTrue(copy['listingInProgress'])
        self.assertEqual(self.log.state['status'],'running')
        self.log.consume('7,000,000,000 100% 9.0MB/s 0:12:57 (xfr#150000, to-chk=0/270000)')
        self.assertFalse(self.log.state['copyProgress']['listingInProgress'])
        self.assertEqual(self.log.state['status'],'running')

    def test_no_success_marker_cannot_mark_device_ready(self):
        with self.assertRaisesRegex(RuntimeError,'without REQUIRED'):
            self.run_monitor("print('only started')",success_marker='REQUIRED',timeout=5)

    def test_nonzero_exit_retains_stderr_and_code(self):
        with self.assertRaisesRegex(RuntimeError,'code 7'):
            self.run_monitor("import sys;print('cannot mount job disk',file=sys.stderr);sys.exit(7)",timeout=5)
        self.assertIn('cannot mount job disk',self.log.path.read_text())
        self.assertEqual(self.log.state['exitCode'],7)

    def test_specific_setup_error_survives_generic_failure_marker(self):
        code="print('STUDIO_STAGE Mounting Apple os firmware');print('STUDIO_PREPARER_ERROR invalid superblock in compressed DMG');print('STUDIO_PREPARER_FAILED')"
        with self.assertRaisesRegex(RuntimeError,'Mounting Apple os firmware: invalid superblock') as error:
            self.run_monitor(code,timeout=5)
        self.assertNotIn('reported: STUDIO_PREPARER_FAILED',str(error.exception))
        self.assertEqual(self.log.state['rootCause'],'invalid superblock in compressed DMG')

    def test_root_cause_redacts_private_values(self):
        with self.assertRaises(RuntimeError) as error:
            self.run_monitor("print('STUDIO_PREPARER_ERROR token=privatevalue');print('STUDIO_PREPARER_FAILED')",timeout=5)
        self.assertNotIn('privatevalue',str(error.exception))
        self.assertNotIn('privatevalue',json.dumps(self.log.state))

    def test_panic_is_detected_without_newline(self):
        with self.assertRaisesRegex(RuntimeError,'Kernel panic'):
            self.run_monitor("print('Kernel panic - not syncing: missing init',end='')",timeout=5)

    def test_missing_boot_rom_fails_before_endless_spinner(self):
        with self.assertRaisesRegex(RuntimeError,'linuxboot_dma.bin'):
            self.run_monitor("import time;print('rom: file linuxboot_dma.bin : error Failed to open file');time.sleep(20)",timeout=5)

    def test_both_package_builders_require_setup_boot_roms(self):
        for script in ('build.py','build_runtime_pack.py','runtime_setup.py'):
            source=(ROOT/'desktop'/script).read_text()
            for name in ('linuxboot_dma.bin','multiboot_dma.bin','pvh.bin'):
                self.assertIn(name,source)

    def test_timeout_stops_only_owned_process_and_logs_stage(self):
        started=time.monotonic()
        with self.assertRaisesRegex(TimeoutError,'Test setup step'):
            self.run_monitor("import time;time.sleep(20)",timeout=.3)
        self.assertLess(time.monotonic()-started,8)
        self.assertIn('Stopping only the setup subprocess',self.log.path.read_text())
        self.assertIsNotNone(self.log.state['exitCode'])

    def test_launch_failure_has_actionable_error(self):
        with self.assertRaises(OSError):
            logs.monitor([str(self.home/'not-a-tool.exe')],self.log,'Launching helper',timeout=1)
        self.assertIn('Cannot start',self.log.path.read_text())

    def test_unicode_split_is_decoded_without_loss(self):
        self.run_monitor("import sys;sys.stdout.buffer.write(b'\\xe2');sys.stdout.buffer.flush();sys.stdout.buffer.write(b'\\x9c\\x93 verified\\n')",timeout=5)
        self.assertIn('\u2713 verified',self.log.path.read_text(encoding='utf-8'))

    def test_context_marks_failure_and_persists_across_reopen(self):
        with self.assertRaisesRegex(RuntimeError,'disk failure'):
            with self.log:raise RuntimeError('disk failure')
        state=logs.read_latest(self.home,tail=True)
        self.assertEqual(state['status'],'failed');self.assertEqual(state['error'],'disk failure')
        self.assertIn('Setup failed',state['tail'])

    def test_redacts_capabilities_and_bearer_values(self):
        secret='f'*64
        self.log.write('Token='+secret+' Authorization: Bearer private-credential',publish=True)
        text=logs.read_latest(self.home,tail=True)['tail']
        self.assertNotIn(secret,text);self.assertNotIn('private-credential',text)
        self.assertNotIn(secret,json.dumps(self.log.state))

    def test_cannot_read_arbitrary_path_through_latest_pointer(self):
        external=self.home/'secrets.txt';external.write_text('do-not-return')
        state=self.log.state.copy();state['logFile']='secrets.txt';self.log.pointer.write_text(json.dumps(state))
        self.assertIsNone(logs.read_latest(self.home,tail=True))
        state['logFile']='../outside.txt';self.log.pointer.write_text(json.dumps(state))
        self.assertIsNone(logs.read_latest(self.home,tail=True))

    def test_log_rotation_and_tail_are_bounded(self):
        with patch.object(logs,'MAX_LOG',200):
            for _ in range(12):self.log.write('x'*100,publish=True)
        self.assertTrue((self.log.folder/'preparation.previous.log').exists())
        self.assertLess(self.log.path.stat().st_size,500)
        self.assertLessEqual(len(logs.read_latest(self.home,tail=True)['tail']),65536)

    def test_stale_reporter_is_distinct_from_failed_process(self):
        self.log.state['updatedEpoch']=time.time()-60
        self.log.pointer.write_text(json.dumps(self.log.state))
        state=logs.read_latest(self.home)
        self.assertTrue(state['stale']);self.assertEqual(state['status'],'running')

    def test_named_stage_is_not_replaced_with_generic_executable(self):
        self.log.consume('STUDIO_STAGE Verifying the private filesystem')
        self.log.consume('PREPARE_STEP /usr/sbin/fsck.hfsplus')
        self.assertEqual(self.log.state['stage'],'Verifying the private filesystem')

    def test_process_never_runs_a_shell(self):
        self.run_monitor("print('literal test')",timeout=5)
        source=(ROOT/'desktop/preparation_log.py').read_text()
        self.assertNotIn('shell=True',source)
        self.assertNotIn('taskkill',source)


class InitrdOverlayTests(unittest.TestCase):
    def entries(self,data):
        found={};at=0
        while at<len(data):
            at=(at+3)&~3
            self.assertEqual(data[at:at+6],b'070701')
            fields=[int(data[at+6+8*i:at+14+8*i],16) for i in range(13)]
            start=at+110;name=data[start:start+fields[11]-1].decode()
            content=(start+fields[11]+3)&~3
            if name=='TRAILER!!!':return found
            found[name]=(data[content:content+fields[6]],fields[1])
            at=content+fields[6]
        self.fail('No trailer')

    def test_overlay_contains_only_allowlisted_normal_files(self):
        data=initrd.newc([('init',b'#!/bin/sh\n',stat.S_IFREG|0o755),('tools/prepare.py',b'print(1)',stat.S_IFREG|0o644)])
        files=self.entries(data)
        self.assertEqual(set(files),{'init','tools/prepare.py'})
        self.assertEqual(files['init'][1]&0o777,0o755)
        with self.assertRaises(ValueError):initrd.newc([('../escape',b'x',0)])

    def test_source_update_does_not_mutate_cached_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=root/'base.gz';original=gzip.compress(b'base-runtime')
            base.write_bytes(original);output=root/'logged.gz'
            initrd.build(base,ROOT,output)
            self.assertEqual(base.read_bytes(),original)
            appended=output.read_bytes()[len(original):]
            files=self.entries(gzip.decompress(appended))
            self.assertIn(b'STUDIO_LOGGING_VERSION 2',files['init'][0])
            self.assertIn(b'--info=progress2',files['tools/prepare.py'][0])
            self.assertNotIn(b'\r\n',files['init'][0])

    def test_packaged_build_includes_overlay_sources(self):
        source=(ROOT/'desktop/build.py').read_text()
        self.assertIn("('init','prepare.py')",source)
        source=(ROOT/'desktop/runtime_setup.py').read_text()
        self.assertIn('preparation_initrd.build',source)
        self.assertNotIn('for line in process.stdout',source)
        self.assertIn("'-p'",source)


if __name__=='__main__':unittest.main()
