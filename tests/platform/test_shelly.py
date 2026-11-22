import importlib.util
from pathlib import Path
import unittest

PATH=Path(__file__).resolve().parents[2]/'ground-station/network-devices/shelly.py'

class ShellyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('crt_shelly',PATH)
        cls.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.module)

    def device(self, replies, **config):
        calls=[]
        def transport(method,params):
            calls.append((method,params))
            response=replies.pop(0)
            if isinstance(response,Exception):raise response
            return response
        return self.module.ShellyDevice({'enabled':True,'address':'192.168.1.120','componentId':0,**config},transport=transport),calls

    def test_unconfigured_entries_make_no_calls(self):
        d,calls=self.device([],enabled=False,address=None)
        self.assertEqual(d.status()['state'],'not_configured')
        with self.assertRaises(ValueError):d.set_output(True)
        self.assertEqual(calls,[])

    def test_status_preserves_off_and_only_finite_supported_metrics(self):
        d,calls=self.device([{'output':False,'apower':0,'voltage':120.1,'current':float('nan'),'aenergy':{'total':2.5}}])
        s=d.status();self.assertEqual(s['output'],False);self.assertEqual(s['metrics'],{'powerW':0,'voltageV':120.1,'energyWh':2.5})
        self.assertEqual(calls,[('Switch.GetStatus',{'id':0})])

    def test_explicit_on_and_off_have_readback(self):
        d,calls=self.device([{}, {'output':True}, {}, {'output':False}])
        self.assertTrue(d.set_output(True)['confirmed']);self.assertTrue(d.set_output(False)['confirmed'])
        self.assertEqual([x for x in calls if x[0]=='Switch.Set'],[('Switch.Set',{'id':0,'on':True}),('Switch.Set',{'id':0,'on':False})])

    def test_readback_mismatch_is_not_confirmed(self):
        d,_=self.device([{}, {'output':False}]);self.assertFalse(d.set_output(True)['confirmed'])

    def test_timeout_write_is_unknown_and_not_retried(self):
        d,calls=self.device([TimeoutError('fixture timeout')])
        with self.assertRaises(self.module.UnknownOutcome):d.set_output(True)
        self.assertEqual(len(calls),1)

    def test_malformed_or_absent_output_never_implies_off(self):
        for result in [{}, {'output':0}, {'output':'false'}]:
            d,_=self.device([result])
            with self.assertRaises(ValueError):d.status()

    def test_enabled_requires_explicit_private_address(self):
        for address in [None,'example.com','8.8.8.8','127.0.0.1','http://192.168.1.1','192.168.1.1/path']:
            with self.assertRaises(ValueError):self.device([],address=address)

    def test_non_boolean_power_command_rejected_before_network(self):
        d,calls=self.device([])
        with self.assertRaises(ValueError):d.set_output('on')
        self.assertEqual(calls,[])

    def test_real_http_rpc_and_sha256_digest_challenge(self):
        import hashlib,json,threading,urllib.request
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                auth=self.headers.get('Authorization','')
                seen.append((body,bool(auth)))
                if not auth:
                    self.send_response(401)
                    self.send_header('WWW-Authenticate','Digest realm="fixture", nonce="fixture-nonce", algorithm=SHA-256, qop="auth"')
                    self.send_header('Content-Length','0');self.end_headers();return
                fields=urllib.request.parse_keqv_list(urllib.request.parse_http_list(auth.removeprefix('Digest ')))
                h=lambda value:hashlib.sha256(value.encode('ascii')).hexdigest()
                expected=h(h('admin:fixture:fixture-password')+':fixture-nonce:'+fields['nc']+':'+fields['cnonce']+':auth:'+h('POST:/rpc'))
                if fields['response']!=expected:
                    self.send_error(403);return
                raw=json.dumps({'id':1,'result':{'output':False,'apower':0}}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            rpc=self.module.http_transport('127.0.0.1:'+str(server.server_port),password='fixture-password')
            self.assertEqual(rpc('Switch.GetStatus',{'id':0})['output'],False)
            self.assertEqual([item[1] for item in seen],[False,True])
            self.assertTrue(all(item[0]['method']=='Switch.GetStatus' for item in seen))
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
