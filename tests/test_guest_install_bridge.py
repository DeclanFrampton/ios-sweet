"""Offline regression tests for the private development bridge's host boundary.

No Apple keys, guest firmware or app binaries are required for these tests.
Actual ARM64 agent execution/registration must also be verified in QEMU.
"""
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import struct
import sys
import tarfile
import tempfile
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT=Path(__file__).resolve().parents[1]

def load(name, file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools/guest-install'/file)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module)
    return module

client=load('sweet_bridge_client_test','client.py')
payload=load('sweet_bridge_payload_test','make-agent-payload.py')
panel=load('sweet_bridge_panel_test','server.py')
relocate=load('sweet_bridge_relocation_test','relocate-frameworks.py')


class BridgeTests(unittest.TestCase):
    def test_framework_relocation_stays_inside_the_staged_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'iOSNova.app';framework=root/'Frameworks/Example.framework/Example'
            framework.parent.mkdir(parents=True);framework.write_bytes(b'example')
            main=root/'iOSNova';main.write_bytes(b'main')
            self.assertEqual(relocate.guest_reference('@rpath/Example.framework/Example',main,root),
                '/Applications/iOSNova.app/Frameworks/Example.framework/Example')
            self.assertIsNone(relocate.guest_reference('/usr/lib/libSystem.B.dylib',main,root))
            with self.assertRaisesRegex(ValueError,'escapes'):
                relocate.guest_reference('@executable_path/../private',main,root)
            with self.assertRaisesRegex(ValueError,'missing'):
                relocate.guest_reference('@rpath/Missing.framework/Missing',main,root)

    def test_macho_dependency_reader_rejects_truncated_commands(self):
        name=b'@rpath/Test.framework/Test\0'
        size=(24+len(name)+7)//8*8
        command=struct.pack('<6I',0xc,size,24,0,0,0)+name
        command=command.ljust(size,b'\0')
        header=struct.pack('<8I',0xfeedfacf,0x100000c,0,2,1,len(command),0,0)
        self.assertEqual(relocate.load_names(header+command),[(0xc,'@rpath/Test.framework/Test')])
        with self.assertRaisesRegex(ValueError,'Invalid'):
            relocate.load_names(header+command[:-1])
        self.assertEqual(relocate.load_names(b'not a Mach-O image'),[])

    def test_helper_entitlements_are_for_app_management_not_general_debug_access(self):
        permissions=plistlib.loads((ROOT/'tools/guest-install/agent-entitlements.plist').read_bytes())
        self.assertTrue(permissions['com.apple.private.MobileContainerManager.allowed'])
        self.assertTrue(permissions['com.apple.frontboard.launchapplications'])
        self.assertEqual(permissions['com.apple.private.mobileinstall.allowedSPI'],['InstallForLaunchServices'])
        for forbidden in ('task_for_pid-allow','com.apple.system-task-ports',
                          'com.apple.frontboard.shutdown','com.apple.private.MobileContainerManager.delete'):
            self.assertNotIn(forbidden,permissions)

    def test_client_refuses_unapproved_operations_or_credentials(self):
        with self.assertRaisesRegex(ValueError,'allowlisted'):
            client.invoke({'Token':'a'*64},'shell')
        with self.assertRaisesRegex(ValueError,'256-bit'):
            client.invoke({'Token':'guessable'},'status')

    def test_client_binds_fixed_route_and_keeps_secret_out_of_url(self):
        calls=[]
        @contextmanager
        def forward(port):
            self.assertEqual(port,4444)
            yield 12345
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,size):return b'{"launchRequested":true}'
        def request(req,timeout):
            calls.append(req)
            self.assertEqual(timeout,20)
            return Response()
        with patch.object(client,'forwarding',forward),patch.object(client,'urlopen',request):
            result=client.invoke({'Token':'b'*64},'launch')
        self.assertTrue(result['launchRequested'])
        self.assertEqual(calls[0].full_url,'http://127.0.0.1:12345/v1/launch')
        self.assertEqual(calls[0].method,'POST')
        self.assertNotIn('b'*64,calls[0].full_url)
        self.assertEqual(calls[0].headers['Authorization'],'Bearer '+'b'*64)

    def test_agent_payload_preserves_jobs_and_private_config_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            original={'LaunchDaemons':{'/System/Library/LaunchDaemons/keep.plist':
                {'Label':'keep','RunAtLoad':True}},'VersionNumber':1}
            (work/'launchd.original.plist').write_bytes(plistlib.dumps(original))
            (work/'iossweet-agent').write_bytes(b'synthetic-agent')
            config={'BundleId':'com.iosnova','BundlePath':'/Applications/iOSNova.app',
                    'Token':'c'*64,'InstanceId':'local-test-not-udid'}
            p=work/'payload/private/var/iossweet';p.mkdir(parents=True)
            (p/'bridge.plist').write_bytes(plistlib.dumps(config))
            self.assertEqual(payload.create(work),4)
            with tarfile.open(work/'agent-payload.tar') as archive:
                member=archive.getmember('private/var/iossweet/bridge.plist')
                self.assertEqual((member.mode,member.uid,member.gid),(0o600,0,0))
                data=plistlib.loads(archive.extractfile('System/Library/xpc/launchd.plist').read())
                self.assertEqual(data['LaunchDaemons']['/System/Library/LaunchDaemons/keep.plist'],
                                 original['LaunchDaemons']['/System/Library/LaunchDaemons/keep.plist'])
                job=data['LaunchDaemons']['/System/Library/LaunchDaemons/org.iossweet.development-agent.plist']
                self.assertEqual(job['JetsamProperties'],{'MemoryLimit':256})
                self.assertEqual(len(data['LaunchDaemons']),2)
                self.assertTrue(all(not n.startswith('/') and '..' not in Path(n).parts for n in archive.getnames()))

    def test_payload_rejects_another_app_path(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            (work/'launchd.original.plist').write_bytes(plistlib.dumps({'LaunchDaemons':{}}))
            p=work/'payload/private/var/iossweet';p.mkdir(parents=True)
            (p/'bridge.plist').write_bytes(plistlib.dumps({'BundleId':'com.iosnova','BundlePath':'/private/secret'}))
            with self.assertRaisesRegex(ValueError,'supplied iOSNova'):
                payload.create(work)


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.server=panel.ThreadingHTTPServer(('127.0.0.1',0),panel.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        panel.Handler.configuration={'Token':'d'*64}

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)

    def request(self,path,body=None,headers=None):
        data=json.dumps(body).encode() if body is not None else None
        try:
            with urlopen(Request(self.base+path,data=data,headers=headers or {}),timeout=3) as r:
                return r.status,r.read()
        except HTTPError as e:return e.code,e.read()

    def test_private_guest_token_never_reaches_html(self):
        code,body=self.request('/')
        self.assertEqual(code,200)
        self.assertIn(b'Launch iOSNova',body)
        self.assertNotIn(b'd'*64,body)
        self.assertNotIn(b'CSRF_NONCE',body)

    def test_rejects_cross_origin_and_missing_csrf_before_guest_access(self):
        with patch.object(panel.bridge,'invoke') as invoke:
            self.assertEqual(self.request('/action/launch',{'csrf':panel.Handler.csrf},
                             {'Origin':'https://foreign.example'})[0],403)
            self.assertEqual(self.request('/action/launch',{'csrf':'wrong'},
                             {'Origin':self.base})[0],403)
            self.assertEqual(self.request('/action/shell',{'csrf':panel.Handler.csrf},
                             {'Origin':self.base})[0],404)
            invoke.assert_not_called()

    def test_only_valid_nonce_and_same_origin_reaches_fixed_guest_operation(self):
        with patch.object(panel.bridge,'invoke',return_value={'launchRequested':True}) as invoke:
            code,body=self.request('/action/launch',{'csrf':panel.Handler.csrf}, {'Origin':self.base})
            self.assertEqual(code,200)
            self.assertTrue(json.loads(body)['launchRequested'])
            self.assertEqual(invoke.call_args.args[1],'launch')


if __name__=='__main__':
    unittest.main()
