#!/usr/bin/env python3
"""Local browser control panel for an explicitly configured iOS Sweet test guest.

The guest capability remains server-side. No remote binding, shell endpoint,
arbitrary bundle identifier, filepath or Apple credential is accepted.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit


spec=importlib.util.spec_from_file_location('iossweet_bridge_client',Path(__file__).with_name('client.py'))
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)


class Handler(BaseHTTPRequestHandler):
    configuration=None
    qmp_port=4444
    csrf=secrets.token_hex(32)

    def allowed_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')

    def respond(self,code,body,mime='application/json; charset=utf-8'):
        data=body if isinstance(body,bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY')
        self.end_headers();self.wfile.write(data)

    def do_GET(self):
        if not self.allowed_host():self.respond(403,{'error':'Localhost only'});return
        if urlsplit(self.path).path!='/':self.respond(404,{'error':'Not found'});return
        html=Path(__file__).with_name('panel.html').read_text(encoding='utf-8')
        html=html.replace('CSRF_NONCE',self.csrf)
        self.respond(200,html.encode(),'text/html; charset=utf-8')

    def do_POST(self):
        port=self.server.server_port
        allowed_origin=self.headers.get('Origin') in (f'http://127.0.0.1:{port}',f'http://localhost:{port}')
        if not self.allowed_host() or not allowed_origin:
            self.respond(403,{'error':'Same-origin local request required'});return
        action=urlsplit(self.path).path.removeprefix('/action/')
        if urlsplit(self.path).path!='/action/'+action or action not in ('status','identity','apps','register','launch','processes','staged'):
            self.respond(404,{'error':'Unknown operation'});return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=1024:raise ValueError('Invalid request size')
            message=json.loads(self.rfile.read(length))
            if not isinstance(message,dict) or set(message)!={'csrf'} or not isinstance(message['csrf'],str) or not secrets.compare_digest(message['csrf'],self.csrf):
                self.respond(403,{'error':'Invalid request token'});return
            result=bridge.invoke(self.configuration,action,self.qmp_port,timeout=30)
            self.respond(200,result)
        except (OSError,ValueError,RuntimeError) as error:
            self.respond(502,{'success':False,'error':str(error),'operation':action})

    def log_message(self,fmt,*args):
        # No request bodies, private capabilities or guest identifiers.
        print('LOCAL_BRIDGE_HTTP',fmt%args,flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--port',type=int,default=8109)
    p.add_argument('--qmp-port',type=int,default=4444)
    args=p.parse_args()
    if not 1024<=args.port<=65535 or not 1<=args.qmp_port<=65535:p.error('Invalid local port')
    Handler.configuration=json.loads(args.config.read_text(encoding='utf-8'))
    Handler.qmp_port=args.qmp_port
    print(f'IOS_SWEET_LOCAL_INSTALL_PANEL=http://127.0.0.1:{args.port}/',flush=True)
    with ThreadingHTTPServer(('127.0.0.1',args.port),Handler) as server:server.serve_forever()


if __name__=='__main__':main()
