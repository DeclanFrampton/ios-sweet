"""Portable Studio regressions; no firmware, SDK, IPA or credentials needed."""
import json
from pathlib import Path
import plistlib
import stat
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
import bundles
import studio

def macho(platform=2,minimum=0x0f0100,encrypted=False,cpu=0x100000c,sub=0):
    commands=struct.pack('<6I',0x32,24,platform,minimum,0x100000,0)
    if encrypted:commands+=struct.pack('<6I',0x2c,24,0,0,1,0)
    return struct.pack('<8I',0xfeedfacf,cpu,sub,2,2 if encrypted else 1,len(commands),0,0)+commands


class BundleTests(unittest.TestCase):
    def ipa(self,folder,extra=None,bid='org.example.demo',binary=None):
        path=Path(folder)/'demo.ipa'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('Payload/Demo.app/Info.plist',plistlib.dumps({'CFBundleIdentifier':bid,'CFBundleExecutable':'Demo','MinimumOSVersion':'15.1'}))
            z.writestr('Payload/Demo.app/Demo',binary or macho())
            for name,value in extra or []:z.writestr(name,value)
        return path

    def test_general_bundle_not_hardcoded(self):
        with tempfile.TemporaryDirectory() as d:
            info=bundles.inspect_ipa(self.ipa(d))
            self.assertEqual(info['bundleId'],'org.example.demo')
            self.assertEqual(info['guestPath'],'/Applications/IOSSweet-org.example.demo.app')

    def test_rejects_path_traversal_and_windows_aliases(self):
        for p in ('../a','/a','C:/a','a\\b','a/../b','a//b','a/./b','NUL.txt','a.','a:stream','a\0b'):
            with self.subTest(p=p),self.assertRaises(ValueError):bundles.safe_path(p)

    def test_archive_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            entry=zipfile.ZipInfo('Payload/Demo.app/link');entry.create_system=3
            entry.external_attr=(stat.S_IFLNK|0o777)<<16
            with self.assertRaisesRegex(ValueError,'Symlink'):
                bundles.inspect_ipa(self.ipa(d,[(entry,b'/etc')]))

    def test_archive_case_collisions_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'Duplicate'):
                bundles.inspect_ipa(self.ipa(d,[('payload/demo.app/info.plist',b'x')]))

    def test_system_bundle_identifiers_rejected(self):
        for s in ('com.apple.Preferences','COM.APPLE.test','../test','abc/xyz','-org.test','org..demo','org.demo.'):
            with self.subTest(s=s),self.assertRaises(ValueError):bundles.bundle_id(s)

    def test_encrypted_app_rejected_without_decryption(self):
        with self.assertRaisesRegex(ValueError,'Encrypted'):bundles.arm64(macho(encrypted=True))

    def test_simulator_newer_ios_and_arm64e_rejected(self):
        for data in (macho(platform=7),macho(minimum=0x110000),macho(sub=2),macho(cpu=0x1000007)):
            with self.assertRaises(ValueError):bundles.arm64(data)

    def test_truncated_command_rejected(self):
        with self.assertRaises(ValueError):bundles.arm64(macho()[:-1])

    def test_preflight_does_not_change_source(self):
        with tempfile.TemporaryDirectory() as d:
            path=self.ipa(d);before=path.read_bytes();bundles.inspect_ipa(path);self.assertEqual(path.read_bytes(),before)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.app=Mock();self.app.status.return_value={'configured':False}
        studio.Handler.studio=self.app
        self.server=studio.ThreadingHTTPServer(('127.0.0.1',0),studio.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2)
    def request(self,path,body=None,headers=None):
        try:
            with urlopen(Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers or {}),timeout=3) as r:
                return r.status,r.read()
        except HTTPError as e:return e.code,e.read()
    def auth(self):return {'Origin':self.base,'X-Studio-Token':studio.Handler.csrf,'Content-Type':'application/json'}
    def test_ui_served_and_nonce_injected(self):
        code,body=self.request('/')
        self.assertEqual(code,200);self.assertIn(b'iOS Sweet Studio',body);self.assertNotIn(b'STUDIO_NONCE',body)
    def test_cross_origin_and_missing_nonce_blocked(self):
        self.assertEqual(self.request('/api/install',{}, {'Origin':'https://external.example'})[0],403)
        self.assertEqual(self.request('/api/install',{}, {'Origin':self.base})[0],403)
        self.app.submit.assert_not_called()
    def test_arbitrary_paths_and_commands_rejected(self):
        self.assertEqual(self.request('/api/shell',{},self.auth())[0],404)
        self.assertEqual(self.request('/api/install',{'path':'C:/private.ipa'},self.auth())[0],400)
        self.app.submit.assert_not_called()
    def test_valid_status(self):
        code,body=self.request('/api/status',{},self.auth())
        self.assertEqual(code,200);self.assertFalse(json.loads(body)['configured'])
    def test_dns_rebinding_host_rejected(self):
        h=self.auth();h['Host']='attacker.example'
        self.assertEqual(self.request('/api/status',{},h)[0],403)

    def test_preparation_log_requires_authentication_and_no_path_argument(self):
        self.assertEqual(self.request('/api/preparation_log',{}, {'Origin':self.base})[0],403)
        self.assertEqual(self.request('/api/preparation_log',{'path':'C:/private.txt'},self.auth())[0],400)
        self.assertEqual(self.request('/api/open_preparation_log',{'path':'C:/private.txt'},self.auth())[0],400)

    def test_preparation_log_returns_only_bounded_redacted_workspace_tail(self):
        import preparation_log
        with tempfile.TemporaryDirectory() as d:
            self.app.home=Path(d)
            diagnostic=preparation_log.PreparationLog(self.app.home,'test',lambda text:None)
            diagnostic.write('Token='+'a'*64,publish=True);diagnostic.finish('failed','missing boot firmware')
            code,body=self.request('/api/preparation_log',{},self.auth())
            self.assertEqual(code,200)
            result=json.loads(body)
            self.assertEqual(result['status'],'failed')
            self.assertNotIn('a'*64,result['tail'])
            self.assertLessEqual(len(result['tail']),65536)


if __name__=='__main__':unittest.main()
