"""iOS Sweet Studio: a native Windows window with a local, authenticated UI."""
from __future__ import annotations
import argparse
from collections import deque
import ctypes
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
from urllib.request import Request, urlopen
import uuid

import bundles

FROZEN = getattr(sys,'frozen',False)
RESOURCE = Path(sys._MEIPASS)/'payload' if FROZEN else Path(__file__).resolve().parent.parent
def default_home():
    if os.environ.get('IOS_SWEET_HOME'):return Path(os.environ['IOS_SWEET_HOME']).resolve()
    if os.name=='nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\IOSSweetStudio') as key:
                path=Path(winreg.QueryValueEx(key,'DataDirectory')[0])
                if path.is_absolute():return path.resolve()
        except (OSError,ValueError,TypeError):pass
    return (Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'iOS Sweet Studio').resolve()

HOME = default_home()
TOOLS = RESOURCE/'tools'


def load_module(name: str, path: Path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


def tool_command(name: str, *args) -> list[str]:
    if name not in ('iossweet-native-windows.py','mkadt.py','mkpayload.py'):
        raise ValueError('Unknown tool')
    if not FROZEN and os.environ.get('IOS_SWEET_SOURCE_ENTRY'):
        return [sys.executable,os.environ['IOS_SWEET_SOURCE_ENTRY'],'--tool',name,*map(str,args)]
    return [sys.executable,*( ['--tool',name] if FROZEN else [str(TOOLS/name)]),*map(str,args)]


class Studio:
    def __init__(self, home: Path=HOME):
        self.home=Path(home);self.home.mkdir(parents=True,exist_ok=True)
        for d in ('logs','jobs','devices','state'): (self.home/d).mkdir(exist_ok=True)
        self.config_path=self.home/'device.json'
        self.config=json.loads(self.config_path.read_text()) if self.config_path.exists() else None
        self.bridge=load_module('studio_bridge',TOOLS/'guest-install/client.py')
        self.lock=threading.Lock();self.job=None;self.events=deque(maxlen=150)
        self.selected=None;self.base=None;self.window=None;self.cached_guest=None
        self.log('iOS Sweet Studio ready. Files and signing stay on this computer.')

    def log(self,text):
        text=str(text).replace('\r',' ').strip()[:1200]
        entry={'time':time.strftime('%H:%M:%S'),'text':text};self.events.append(entry)
        with (self.home/'logs/studio.log').open('a',encoding='utf-8') as f:f.write(entry['time']+' '+text+'\n')

    def save(self):
        temp=self.config_path.with_suffix('.new');temp.write_text(json.dumps(self.config,indent=2));os.replace(temp,self.config_path)

    def runtime(self):
        if not self.config:raise RuntimeError('Create or import an iOS device first.')
        return self.config

    def active(self):
        c=self.config
        if not c:return None
        p=Path(c['state'])/'active-native.json'
        if not p.exists():return None
        r=json.loads(p.read_text())
        # Reuse/stop only a PID whose executable belongs to this configured QEMU.
        from ctypes import wintypes
        k=ctypes.windll.kernel32;k.OpenProcess.restype=ctypes.c_void_p
        k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        k.QueryFullProcessImageNameW.argtypes=[ctypes.c_void_p,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes=[ctypes.c_void_p]
        h=k.OpenProcess(0x1000,False,int(r['qemu_pid']))
        if not h:return None
        try:
            size=wintypes.DWORD(32768);buf=ctypes.create_unicode_buffer(size.value)
            if not k.QueryFullProcessImageNameW(h,0,buf,ctypes.byref(size)):raise RuntimeError('Cannot verify QEMU process.')
            if not Path(buf.value).samefile(Path(c['qemu'])/'qemu-system-aarch64.exe'):raise RuntimeError('Active PID belongs to a different application.')
        finally:k.CloseHandle(h)
        run=Path(r['run']).resolve()
        if not run.is_relative_to(Path(c['state']).resolve()):raise RuntimeError('Active run escaped its state directory.')
        arguments=json.loads((run/'command.json').read_text())
        expected='file='+str(Path(c['overlay']).resolve()).replace('\\','/')
        if not any(a.startswith('if=none,id=iosroot,') and expected in a for a in arguments):
            raise RuntimeError('The running guest uses a different disk; it was left untouched.')
        return r

    def status(self):
        try:r=self.active();error=None
        except Exception as e:r=None;error=str(e)
        return {'product':'iOS Sweet Studio','version':'0.2.0-preview','configured':bool(self.config),
            'vmRunning':bool(r),'guest':self.cached_guest,'job':self.job,'events':list(self.events),
            'selected':self.selected['info'] if self.selected else None,'error':error,
            'dataDirectory':str(self.home),'platform':'Windows x64 / iOS 16.7.16'}

    def submit(self, action, **kwargs):
        allowed={'start','shutdown','install','refresh','launch','stop_app','create_device','prepare_apple','import_device','export_device'}
        if action not in allowed:raise ValueError('Unknown action')
        if not self.lock.acquire(blocking=False):raise RuntimeError('Another operation is already running.')
        self.job={'id':uuid.uuid4().hex,'action':action,'state':'running','message':'Starting'}
        def run():
            try:
                result=getattr(self,action)(**kwargs)
                self.job.update(state='succeeded',result=result,message='Completed')
            except Exception as e:
                self.job.update(state='failed',message=str(e));self.log('ERROR: '+str(e))
            finally:self.lock.release()
        threading.Thread(target=run,daemon=True).start()
        return dict(self.job)

    def progress(self,text):
        if self.job:self.job['message']=str(text)
        self.log(text)

    def guest(self,action,bid=None,packet=None,timeout=30):
        c=self.runtime();self.active() or (_ for _ in ()).throw(RuntimeError('Start the iPhone first.'))
        cfg=json.loads(Path(c['bridgeConfig']).read_text())
        token=cfg.get('Token','')
        if not __import__('re').fullmatch('[0-9a-f]{64}',token):raise ValueError('Invalid private guest capability.')
        if bid:bundles.bundle_id(bid)
        route={'install':'/v2/install','stop_app':'/v2/stop'}.get(action,'/v1/'+action)
        if action not in ('status','identity','apps','launch','register','processes','install','stop_app'):raise ValueError('Unsupported guest operation')
        method='POST' if action in ('install','stop_app','launch','register') else 'GET'
        with self.bridge.forwarding(c.get('qmpPort',4444)) as port:
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=timeout)
            try:
                size=Path(packet).stat().st_size if packet else 0
                conn.putrequest(method,route)
                conn.putheader('Authorization','Bearer '+token)
                conn.putheader('Content-Length',str(size))
                if bid:conn.putheader('X-IOSSweet-Bundle',bid)
                conn.endheaders()
                if packet:
                    sent=0
                    with Path(packet).open('rb') as f:
                        for chunk in iter(lambda:f.read(256*1024),b''):
                            conn.send(chunk);sent+=len(chunk)
                            if self.job:self.job['message']=f'Transferring app to iPhone: {sent*100//size}%'
                    self.progress('Transfer complete; iOS is registering the app')
                response=conn.getresponse();body=json.loads(response.read(2*1024**2))
                if response.status!=200 or body.get('error'):raise RuntimeError(body.get('error',f'Guest HTTP {response.status}'))
                return body
            finally:conn.close()

    def wait_ready(self,seconds=600):
        end=time.monotonic()+seconds;last='Guest starting'
        while time.monotonic()<end:
            try:
                r=self.guest('status',timeout=5)
                if r.get('version',0)<7:raise ValueError('This guest needs the Studio v7 agent. Create a Studio device from a prepared root image.')
                self.cached_guest=r;return r
            except (ConnectionError,OSError,RuntimeError,http.client.HTTPException) as e:last=str(e)
            time.sleep(3)
        raise RuntimeError('iOS has not reached guest-agent readiness. '+last)

    def start(self):
        c=self.runtime()
        if self.active():
            self.progress('Reusing the existing iPhone; no duplicate VM.')
        else:
            for name in ('disk','overlay','kernel','bridgeConfig'):
                if not Path(c[name]).is_file():raise RuntimeError('Missing device file: '+name)
            if bundles.sha256(Path(c['kernel']))!=c['kernelSha256']:raise RuntimeError('Kernel SHA-256 mismatch.')
            env=dict(os.environ,IOS_SWEET_QEMU_DIR=c['qemu'],IOS_SWEET_DATA_ROOT=str(self.home))
            cmd=tool_command('iossweet-native-windows.py','--kernel',c['kernel'],'--kernel-sha256',c['kernelSha256'],
                '--disk',c['disk'],'--overlay',c['overlay'],'--state',c['state'],'--cpus','2','--srgb-display','--no-browser',
                '--port',str(c.get('viewerPort',8108)),'--qmp-port',str(c.get('qmpPort',4444)))
            out=self.home/'logs/native.log';err=self.home/'logs/native-error.log'
            with out.open('w') as fo,err.open('w') as fe:
                p=subprocess.Popen(cmd,stdout=fo,stderr=fe,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.progress('Starting native Windows QEMU. iOS first boot may take several minutes.')
            for _ in range(80):
                if p.poll() is not None:raise RuntimeError(err.read_text(errors='replace')[-1200:])
                if self.active():break
                time.sleep(.5)
            else:raise RuntimeError('Viewer did not start. See native-error.log; no second guest was created.')
        self.wait_ready();self.progress('iPhone is ready.');return self.refresh()

    def shutdown(self):
        c=self.runtime()
        if not self.active():return {'stopped':True}
        env=dict(os.environ,IOS_SWEET_QEMU_DIR=c['qemu'],IOS_SWEET_DATA_ROOT=str(self.home))
        result=subprocess.run(tool_command('iossweet-native-windows.py','--state',c['state'],'--stop'),
            env=env,capture_output=True,text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError(result.stderr[-1000:])
        for _ in range(60):
            if not self.active():self.cached_guest=None;self.progress('iPhone stopped; its data is preserved.');return {'stopped':True}
            time.sleep(.5)
        raise RuntimeError('QEMU has not finished stopping. No files were changed.')

    def refresh(self):
        self.cached_guest=self.guest('status',timeout=8)
        r=self.guest('apps',timeout=60)
        return r

    def launch(self,bundleId):
        bundles.bundle_id(bundleId);self.progress('Opening '+bundleId)
        r=self.guest('launch',bundleId,timeout=60)
        if not r.get('launchRequested'):raise RuntimeError('iOS did not accept the launch request.')
        for _ in range(12):
            time.sleep(1);p=self.guest('processes',bundleId,timeout=10)
            if p.get('running'):self.progress('App process is running. Check the embedded iPhone screen.');return p
        raise RuntimeError('Launch was requested, but no running app process was found. This IPA may be incompatible.')

    def stop_app(self,bundleId):return self.guest('stop_app',bundles.bundle_id(bundleId))

    def install(self):
        if not self.selected:raise ValueError('Choose an IPA first.')
        self.wait_ready(20)
        path=Path(self.selected['path']);info=self.selected['info']
        if bundles.sha256(path)!=info['sourceSha256']:raise ValueError('Selected IPA changed; select it again.')
        job=self.home/'jobs'/uuid.uuid4().hex
        signer=self.signer()
        info,packet=bundles.prepare(path,job,signer,self.progress)
        r=self.guest('install',packet=packet,timeout=600)
        if not r.get('registrationReturned'):raise RuntimeError('Bundle transferred, but iOS registration failed. Original IPA is unchanged.')
        installed=self.guest('apps',timeout=60)
        if not any(a.get('bundleId')==info['bundleId'] for a in installed.get('applications',[])):
            raise RuntimeError('Registration was not independently confirmed.')
        self.progress('Installed and registered '+info['name'])
        # Free expanded intermediate files; retain the small job metadata/logs.
        packet.unlink(missing_ok=True)
        private=job/('IOSSweet-'+info['bundleId']+'.app')
        if private.parent==job and private.is_dir() and not private.is_symlink():shutil.rmtree(private)
        return {'apps':installed,'launch':self.launch(info['bundleId'])}

    def signer(self):
        if os.environ.get('IOS_SWEET_ASSET_ROOT'):
            p=Path(os.environ['IOS_SWEET_ASSET_ROOT']).resolve()/'rcodesign.exe'
            if not p.is_file():raise RuntimeError('The downloaded runtime signer is missing. Run start.cmd again.')
            return p
        choices=[RESOURCE/'desktop/assets/rcodesign.exe',*RESOURCE.glob('windows-runtime/desktop-build/signer/**/rcodesign.exe')]
        for p in choices:
            if p.is_file():return p
        raise RuntimeError('Bundled Windows signer is missing. Reinstall the Studio package.')

    def choose(self,kind):
        import webview
        if self.lock.locked():raise RuntimeError('Finish the current operation before changing files.')
        if kind=='ipa':
            paths=self.window.create_file_dialog(webview.FileDialog.OPEN,allow_multiple=False,file_types=('iOS application (*.ipa)',))
            if not paths:return {'cancelled':True}
            info=bundles.inspect_ipa(Path(paths[0]));self.selected={'path':paths[0],'info':info}
            self.log('Selected '+info['name']+' ('+info['bundleId']+')');return info
        if kind=='root':
            paths=self.window.create_file_dialog(webview.FileDialog.OPEN,allow_multiple=False,file_types=('Prepared iOS root (*.raw;*.img)',))
            if paths:self.base=paths[0]
            return {'selected':bool(paths),'name':Path(paths[0]).name if paths else None}
        raise ValueError('Unknown file selection')

    def create_device(self):
        if not self.base:raise ValueError('Select your prepared iOS 16.7.16 root image first.')
        import runtime_setup
        self.config=runtime_setup.from_prepared_root(Path(self.base),self.home,RESOURCE,self.progress)
        self.save();self.progress('Device created. Press Start iPhone.');return {'configured':True}

    def prepare_apple(self):
        import runtime_setup
        self.config=runtime_setup.from_apple(self.home,RESOURCE,self.progress)
        self.save();self.progress('Device created from Apple firmware.');return self.start()

    def import_device(self):
        raise ValueError('Choose a prepared .raw image in Setup, then select Create device.')

    def export_device(self):
        raise ValueError('Device backups are private. The original base image is kept read-only; user data remains in the overlay.')

    def viewer(self,kind,data=None):
        c=self.runtime();self.active() or (_ for _ in ()).throw(RuntimeError('iPhone is stopped.'))
        base=f'http://127.0.0.1:{c.get("viewerPort",8108)}'
        if kind=='frame':
            with urlopen(base+'/frame.png',timeout=4) as r:return r.read(20*1024**2)
        if kind not in ('touch','gesture'):raise ValueError('Invalid input')
        req=Request(base+'/'+kind,data=json.dumps(data).encode(),headers={'Origin':base,'Content-Type':'application/json'})
        with urlopen(req,timeout=8) as r:
            body=r.read(8192);return json.loads(body) if body else {'accepted':True}


class Handler(BaseHTTPRequestHandler):
    studio=None;csrf=secrets.token_hex(32)
    def send(self,code,body,mime='application/json'):
        b=body if isinstance(body,bytes) else json.dumps(body).encode()
        self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(b)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'nonce-"+self.csrf+"'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        try:self.wfile.write(b)
        except (BrokenPipeError,ConnectionResetError):pass
    def local(self):return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
    def do_GET(self):
        if not self.local():self.send(403,{'error':'Local access only'});return
        if self.path!='/':self.send(404,{'error':'Not found'});return
        html=(RESOURCE/'desktop/index.html').read_text(encoding='utf-8').replace('STUDIO_NONCE',self.csrf)
        self.send(200,html.encode(),'text/html; charset=utf-8')
    def do_POST(self):
        try:
            origin=f'http://127.0.0.1:{self.server.server_port}'
            if not self.local() or self.headers.get('Origin')!=origin or not secrets.compare_digest(self.headers.get('X-Studio-Token',''),self.csrf):
                self.send(403,{'error':'Same-origin authenticated request required'});return
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=2048:raise ValueError('Invalid request size')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError('Expected a JSON object')
            action=self.path.removeprefix('/api/')
            if self.path!='/api/'+action:raise ValueError('Invalid route')
            if action=='status':result=self.studio.status()
            elif action=='select':result=self.studio.choose(data.get('kind'))
            elif action=='frame':self.send(200,self.studio.viewer('frame'),'image/png');return
            elif action in ('touch','gesture'):result=self.studio.viewer(action,data)
            elif action=='logs':os.startfile(self.studio.home/'logs');result={'opened':True}
            elif action in ('launch','stop_app'):
                if set(data)!={'bundleId'}:raise ValueError('Expected a bundle ID')
                result=self.studio.submit(action,bundleId=bundles.bundle_id(data['bundleId']))
            elif action in ('start','shutdown','install','refresh','create_device','prepare_apple'):
                if data:raise ValueError('This operation accepts no arguments')
                result=self.studio.submit(action)
            else:self.send(404,{'error':'Unknown operation'});return
            self.send(200,result)
        except Exception as e:self.send(400,{'error':str(e)})
    def log_message(self,*args):pass


def main():
    # PyInstaller's windowed bootloader leaves sys.stdout/stderr unset, even
    # when our owned tool subprocess has inherited redirected OS handles.
    if FROZEN and ('--tool' in sys.argv or '--self-test' in sys.argv):
        import io,msvcrt
        for attr,handle_id in (('stdout',-11),('stderr',-12)):
            if getattr(sys,attr) is None:
                try:
                    k=ctypes.windll.kernel32;k.GetStdHandle.restype=ctypes.c_void_p
                    fd=msvcrt.open_osfhandle(k.GetStdHandle(handle_id),os.O_WRONLY)
                    setattr(sys,attr,io.TextIOWrapper(os.fdopen(fd,'wb'),encoding='utf-8',write_through=True))
                except (OSError,ValueError):setattr(sys,attr,open(os.devnull,'w'))
    if len(sys.argv)>2 and sys.argv[1]=='--tool':
        name=sys.argv[2]
        if name not in ('iossweet-native-windows.py','mkadt.py','mkpayload.py'):raise SystemExit(64)
        sys.argv=[str(TOOLS/name),*sys.argv[3:]];sys.path.insert(0,str(TOOLS))
        import runpy
        runpy.run_path(str(TOOLS/name),run_name='__main__');return
    if '--self-test' in sys.argv:
        assert (RESOURCE/'desktop/index.html').is_file()
        assert bundles.safe_path('Payload/Example.app/Info.plist')
        print('STUDIO_PACKAGE_SELF_TEST_OK');return
    if os.name!='nt':raise SystemExit('This packaged preview targets Windows 10/11 x64.')
    k=ctypes.windll.kernel32;k.CreateMutexW.restype=ctypes.c_void_p
    mutex=k.CreateMutexW(None,False,'Local\\IOSSweetStudioDesktop')
    if k.GetLastError()==183:
        ctypes.windll.user32.MessageBoxW(0,'iOS Sweet Studio is already open.','iOS Sweet Studio',64);return
    app=Studio();Handler.studio=app
    if len(sys.argv)==3 and sys.argv[1]=='--ipa':
        try:
            path=Path(sys.argv[2]).resolve(strict=True)
            app.selected={'path':str(path),'info':bundles.inspect_ipa(path)}
        except Exception as e:app.log('IPA selection failed: '+str(e))
    with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
        session_file=app.home/'state/desktop.json'
        session_file.write_text(json.dumps({'pid':os.getpid(),'port':server.server_port,'uiReady':False}))
        app.log('Desktop interface listening on local port '+str(server.server_port))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        import webview
        app.window=webview.create_window('iOS Sweet Studio',f'http://127.0.0.1:{server.server_port}',
            width=1280,height=900,min_size=(1000,740),background_color='#0b1020')
        def window_loaded(*_):
            # A listening HTTP server alone does not prove the native display
            # loaded. The source bootstrap waits for this WebView event too.
            temporary=session_file.with_suffix('.ready')
            temporary.write_text(json.dumps({'pid':os.getpid(),'port':server.server_port,'uiReady':True}))
            os.replace(temporary,session_file)
            app.log('Native Studio window loaded successfully.')
        app.window.events.loaded+=window_loaded
        def closing():
            if app.lock.locked():
                ctypes.windll.user32.MessageBoxW(0,'An operation is still running. Finish it before closing Studio.','iOS Sweet Studio',48);return False
            return True
        app.window.events.closing+=closing
        webview.start(gui='edgechromium',debug=False,private_mode=True)
        server.shutdown()
        (app.home/'state/desktop.json').unlink(missing_ok=True)
    k.CloseHandle.argtypes=[ctypes.c_void_p];k.CloseHandle(mutex)


if __name__=='__main__':main()
