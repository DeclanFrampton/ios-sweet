"""Reconnect regressions: synthetic metadata only, no QEMU or private devices."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
import bundles
import device_connection as connection
import studio


class DeviceConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name).resolve()
        self.original=self.home/'original';self.root=self.original/'devices/test-device'
        self.run=self.root/'state/windows-qemu-test';self.run.mkdir(parents=True)
        self.qemu=self.home/'runtime/qemu';self.qemu.mkdir(parents=True)
        for name in ('ios.raw','ios.qcow2','kernel.sweet'):(self.root/name).write_bytes(b'synthetic')
        self.executable=self.qemu/'qemu-system-aarch64.exe';self.executable.write_bytes(b'not-executable')
        self.bridge=self.root/'bridge.json'
        self.bridge.write_text(json.dumps({'Token':'a'*64,'InstanceId':'synthetic-instance'}))
        self.config={'schema':2,'disk':str(self.root/'ios.raw'),'overlay':str(self.root/'ios.qcow2'),
            'kernel':str(self.root/'kernel.sweet'),'kernelSha256':bundles.sha256(self.root/'kernel.sweet'),
            'bridgeConfig':str(self.bridge),'state':str(self.root/'state'),
            'qemu':str(self.qemu),'viewerPort':8108,'qmpPort':4444,'instanceId':'synthetic-instance'}
        self.state={'qemu_pid':123,'run':str(self.run),'viewer_port':8108,'qmp_port':4444,
            'kernel_sha256':self.config['kernelSha256']}
        self.args=[str(self.executable),'-serial','file:'+str(self.run/'serial.txt'),
            '-qmp','tcp:127.0.0.1:4444,server=on,wait=off','-drive',
            'if=none,id=iosroot,format=qcow2,file='+str(self.root/'ios.qcow2')+',snapshot=off']
        (self.run/'command.json').write_text(json.dumps(self.args[1:]))
        (self.root/'state/active-native.json').write_text(json.dumps(self.state))
        (self.original/'device.json').write_text(json.dumps(self.config))
        self.process={'ProcessId':123,'ExecutablePath':str(self.executable),'CommandLine':'synthetic'}

    def tearDown(self):self.temp.cleanup()

    def validate(self,config=None,state=None,args=None):
        return connection.validate_config(config or self.config,state or self.state,args or self.args,str(self.executable),123)

    def test_running_device_discovered_in_original_home(self):
        found=connection.candidate(self.process,self.args)
        self.assertEqual(found['pid'],123)
        self.assertEqual(found['source'],str(self.original/'device.json'))
        self.assertEqual(found['config']['overlay'],self.config['overlay'])

    def test_stale_pid_is_rejected(self):
        state=dict(self.state,qemu_pid=456)
        with self.assertRaisesRegex(ValueError,'PID'):self.validate(state=state)

    def test_similar_overlay_prefix_cannot_pass(self):
        wrong=self.root/'ios.qcow2.other';wrong.write_bytes(b'not-the-device')
        args=self.args[:-1]+[self.args[-1].replace('ios.qcow2','ios.qcow2.other')]
        with self.assertRaisesRegex(ValueError,'different overlay'):self.validate(args=args)

    def test_port_and_command_mismatch_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'port'):self.validate(config=dict(self.config,viewerPort=9999))
        (self.run/'command.json').write_text(json.dumps(self.args[1:]+['-snapshot']))
        with self.assertRaisesRegex(ValueError,'command differs'):self.validate()

    def test_other_executable_is_rejected(self):
        other=self.home/'other/qemu-system-aarch64.exe';other.parent.mkdir();other.write_bytes(b'other')
        with self.assertRaisesRegex(ValueError,'executable'):
            connection.validate_config(self.config,self.state,self.args,str(other),123)

    def test_missing_or_mismatched_guest_capability_is_rejected(self):
        self.bridge.write_text(json.dumps({'Token':'bad','InstanceId':'synthetic-instance'}))
        with self.assertRaisesRegex(ValueError,'bridge identity'):self.validate()

    def test_discovery_refuses_multiple_emulators(self):
        with patch.object(connection,'processes',return_value=[self.process,self.process]):
            result=connection.discover()
        self.assertTrue(result['running']);self.assertFalse(result['canConnect'])

    def test_new_window_reports_running_elsewhere_without_secrets(self):
        app=studio.Studio(self.home/'new-clone')
        found={'running':True,'canConnect':True,'message':'Connect to existing device',
            'candidate':{'config':self.config,'pid':123,'source':str(self.original/'device.json')}}
        with patch.object(app,'discovery',return_value=found):status=app.status()
        self.assertFalse(status['configured']);self.assertFalse(status['vmRunning'])
        self.assertTrue(status['connection']['runningElsewhere']);self.assertTrue(status['connection']['canConnect'])
        self.assertNotIn('a'*64,json.dumps(status));self.assertNotIn('bridgeConfig',json.dumps(status))

    def test_verified_reconnect_saves_reference_without_reboot_or_copying_disk(self):
        app=studio.Studio(self.home/'new-clone')
        original=(self.original/'device.json').read_bytes();disk=(self.root/'ios.qcow2').read_bytes()
        found={'running':True,'canConnect':True,'message':'',
            'candidate':{'config':self.config,'pid':123,'source':str(self.original/'device.json')}}
        health={'version':7,'multiAppInstall':True,'vmInstanceId':'synthetic-instance'}
        with patch.object(app,'discovery',return_value=found),patch.object(app,'guest',return_value=health), \
             patch.object(app,'refresh',return_value={'applications':[]}),patch.object(studio.subprocess,'Popen') as launch:
            app.connect_running();launch.assert_not_called()
        self.assertEqual(json.loads(app.config_path.read_text())['overlay'],self.config['overlay'])
        self.assertEqual((self.original/'device.json').read_bytes(),original)
        self.assertEqual((self.root/'ios.qcow2').read_bytes(),disk)

    def test_wrong_guest_does_not_replace_config(self):
        app=studio.Studio(self.home/'new-clone')
        found={'running':True,'canConnect':True,'message':'','candidate':{'config':self.config,'pid':123}}
        with patch.object(app,'discovery',return_value=found),patch.object(app,'guest',return_value={
            'version':7,'multiAppInstall':True,'vmInstanceId':'another-guest'}):
            with self.assertRaisesRegex(RuntimeError,'authenticate'):app.connect_running()
        self.assertIsNone(app.config);self.assertFalse(app.config_path.exists())

    def test_setup_blocked_before_any_firmware_download_when_another_iphone_exists(self):
        app=studio.Studio(self.home/'new-clone')
        with patch.object(app,'discovery',return_value={'running':True,'canConnect':True,'message':''}), \
             patch('runtime_setup.from_apple') as download:
            with self.assertRaisesRegex(RuntimeError,'Connect to running'):app.prepare_apple()
            download.assert_not_called()

    def test_connect_backs_up_existing_selection(self):
        app=studio.Studio(self.home/'new-clone');app.config={'previous':'device'};app.save()
        found={'running':True,'canConnect':True,'message':'','candidate':{'config':self.config,'pid':123}}
        with patch.object(app,'discovery',return_value=found),patch.object(app,'guest',return_value={
            'version':7,'multiAppInstall':True,'vmInstanceId':'synthetic-instance'}), \
             patch.object(app,'refresh',return_value={'applications':[]}):
            app.connect_running()
        backups=list(app.home.glob('device.before-connect-*.json'))
        self.assertEqual(len(backups),1);self.assertEqual(json.loads(backups[0].read_text()),{'previous':'device'})


if __name__=='__main__':unittest.main()
