"""Local network-device API. No device discovery, automatic writes or Omada guesses."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit
from shelly import ShellyDevice, UnknownOutcome

ID=re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')


class DeviceRegistry:
    def __init__(self, inventory, *, credentials=None, adapter_factory=None, clock=time.monotonic):
        if not isinstance(inventory,dict) or inventory.get('schemaVersion')!=1 or not isinstance(inventory.get('devices'),list):
            raise ValueError('Invalid inventory schema')
        self.clock=clock;self.devices={};self.adapters={};self.cached={};self.locks={}
        credentials=credentials or {}
        if not isinstance(credentials,dict):raise ValueError('Invalid credentials document')
        factory=adapter_factory or (lambda device,auth:ShellyDevice(device,**auth))
        for device in inventory['devices']:
            if not isinstance(device,dict) or not isinstance(device.get('id'),str) or not ID.fullmatch(device['id']):
                raise ValueError('Invalid device ID')
            name=device['id']
            if name in self.devices:raise ValueError('Duplicate device ID')
            if device.get('kind') not in ('shelly','omada-switch','omada-bridge'):raise ValueError('Unsupported device kind')
            if device['kind']=='shelly' and type(device.get('enabled',False)) is not bool:raise ValueError('Invalid enabled flag')
            self.devices[name]=device;self.locks[name]=threading.RLock()
            if device['kind']=='shelly' and device.get('enabled') is True:
                auth=credentials.get(name,{})
                if not isinstance(auth,dict) or set(auth)-{'username','password'}:raise ValueError('Invalid device credential fields')
                if any(not isinstance(v,str) for v in auth.values()):raise ValueError('Invalid credential value')
                self.adapters[name]=factory(device,auth)

    def _public(self,name,status):
        device=self.devices[name]
        result={k:device[k] for k in ('id','kind','model','address','connectedLoad') if k in device}
        if device['kind']=='omada-switch':
            result['ports']=[{**port,'powerControlEnabled':False} for port in device.get('ports',[])]
        result.update(status)
        result['canSetOutput']=name in self.adapters
        return result

    def read(self,name):
        if name not in self.devices:raise KeyError(name)
        if name not in self.adapters:
            state='not_configured' if self.devices[name]['kind']=='shelly' else 'inspection_pending'
            return self._public(name,{'state':state,'output':None,'metrics':{},'stale':True,'lastSuccessUnixMs':None})
        with self.locks[name]:
            now=self.clock();cached=self.cached.get(name)
            if cached is None or now-cached['checked']>=2:
                last=cached['status'].get('lastSuccessUnixMs') if cached else None
                try:
                    status={**self.adapters[name].status(),'stale':False,'lastSuccessUnixMs':int(time.time()*1000)}
                except Exception:
                    status={'state':'unavailable','output':None,'metrics':{},'stale':True,'lastSuccessUnixMs':last}
                self.cached[name]={'checked':now,'status':status}
            return self._public(name,self.cached[name]['status'])

    def snapshot(self):
        return {'schemaVersion':1,'devices':[self.read(name) for name in self.devices]}

    def set_output(self,name,on):
        if name not in self.devices:raise KeyError(name)
        if name not in self.adapters or type(on) is not bool:raise ValueError('Device power control unavailable')
        with self.locks[name]:
            try:
                result=self.adapters[name].set_output(on)
            except UnknownOutcome:
                self.cached[name]={'checked':self.clock(),'status':{'state':'unknown','output':None,'metrics':{},'stale':True,'lastSuccessUnixMs':None}}
                raise
            self.cached[name]={'checked':self.clock(),'status':{**result['observed'],'stale':False,'lastSuccessUnixMs':int(time.time()*1000)}}
            return result


def handler_for(registry, *, operator_token=None):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(5)

        def log_message(self,*args):
            pass  # Never log request headers or device responses/credentials.

        def reply(self,status,body):
            raw=json.dumps(body,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)

        def do_GET(self):
            parts=urlsplit(self.path)
            if parts.query:return self.reply(400,{'error':'Queries are not supported'})
            if parts.path=='/v1/devices':return self.reply(200,{**registry.snapshot(),'powerWritesConfigured':bool(operator_token),'operatorAuthorizationRequired':True})
            match=re.fullmatch(r'/v1/devices/([A-Za-z0-9_-]+)',parts.path)
            if match:
                try:return self.reply(200,registry.read(match[1]))
                except KeyError:pass
            self.reply(404,{'error':'Unknown endpoint or device'})

        def do_POST(self):
            # No CORS support: browsers cannot send cross-origin bearer requests.
            supplied=self.headers.get('Authorization','')
            if not operator_token or not hmac.compare_digest(supplied.encode('utf-8'),('Bearer '+operator_token).encode('utf-8')):
                return self.reply(403,{'error':'Operator authorization required'})
            parts=urlsplit(self.path)
            match=re.fullmatch(r'/v1/devices/([A-Za-z0-9_-]+)/output',parts.path)
            if not match or parts.query:return self.reply(404,{'error':'Unknown endpoint'})
            if self.headers.get_content_type()!='application/json':return self.reply(415,{'error':'JSON required'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=4096:return self.reply(413,{'error':'Invalid request size'})
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict) or set(body)!={'on'} or type(body['on']) is not bool:
                    return self.reply(400,{'error':'Explicit boolean on required'})
                result=registry.set_output(match[1],body['on'])
            except KeyError:return self.reply(404,{'error':'Unknown device'})
            except UnknownOutcome:return self.reply(503,{'error':'Power outcome unknown; read state before another request','outcome':'unknown'})
            except (ValueError,TimeoutError):return self.reply(400,{'error':'Invalid request or unavailable control'})
            self.reply(200,result)
    return Handler


def read_private_json(path):
    file=Path(path)
    if str(file.resolve()).startswith('/nix/store/') or file.stat().st_mode&0o077:
        raise ValueError('Credentials must be private runtime files outside the Nix store')
    if file.stat().st_size>16384:raise ValueError('Credentials file exceeds size limit')
    return json.loads(file.read_text())


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',type=Path,default=Path(__file__).with_name('inventory.json'))
    parser.add_argument('--credentials-file',type=Path)
    parser.add_argument('--port',type=int,default=8767)
    parser.add_argument('--check-config',action='store_true')
    args=parser.parse_args(argv)
    try:
        credentials=read_private_json(args.credentials_file) if args.credentials_file else {}
        if not isinstance(credentials,dict) or set(credentials)-{'devices','operatorToken'}:raise ValueError('Invalid credentials document')
        token=credentials.get('operatorToken')
        if token is not None and (not isinstance(token,str) or not token.isascii() or len(token)<24):raise ValueError('Invalid operator token')
        registry=DeviceRegistry(json.loads(args.inventory.read_text()),credentials=credentials.get('devices',{}))
    except (ValueError,OSError):
        parser.exit(1,'Invalid network-device configuration; check inventory and runtime credential file\n')
    if args.check_config:
        print(json.dumps({'valid':True,'deviceIds':list(registry.devices),'powerWritesEnabled':bool(token)}));return 0
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(registry,operator_token=token))
    server.daemon_threads=True
    try:server.serve_forever()
    finally:server.server_close()
    return 0


if __name__=='__main__':raise SystemExit(main())
