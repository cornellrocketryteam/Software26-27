import importlib.util
import json
from pathlib import Path
import sys
import unittest

DIRECTORY=Path(__file__).resolve().parents[2]/'ground-station/network-devices'
sys.path.insert(0,str(DIRECTORY))

class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('crt_network_service',DIRECTORY/'service.py')
        cls.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.module)

    def fixture(self):
        self.calls=[];self.now=0
        parent=self
        class Adapter:
            fail=False
            def status(self):
                parent.calls.append('read')
                if self.fail:raise TimeoutError()
                return {'state':'available','output':False,'metrics':{'powerW':0}}
            def set_output(self,on):
                parent.calls.append(('write',on))
                if self.fail:raise parent.module.UnknownOutcome('fixture')
                return {'requestedOutput':on,'confirmed':True,'observed':{'state':'available','output':on,'metrics':{}}}
        self.adapter=Adapter()
        inventory={'schemaVersion':1,'devices':[{'id':'plug','kind':'shelly','model':'fixture','enabled':True,'address':'192.168.1.120','componentId':0,'powerControlEnabled':True,'connectedLoad':'Fixture lamp'}]}
        return self.module.DeviceRegistry(inventory,adapter_factory=lambda d,c:self.adapter,clock=lambda:self.now)

    def test_current_inventory_has_no_network_activity(self):
        inventory=json.loads((DIRECTORY/'inventory.json').read_text())
        def forbidden(*args):raise AssertionError('configured adapter unexpectedly started')
        registry=self.module.DeviceRegistry(inventory,adapter_factory=forbidden)
        rows=registry.snapshot()['devices'];self.assertEqual(len(rows),7)
        self.assertTrue(all(row['state'] in ('not_configured','inspection_pending') for row in rows))
        self.assertTrue(all(row['output'] is None for row in rows))

    def test_writes_require_explicit_opt_in_and_load_mapping(self):
        registry=self.fixture()
        registry.devices['plug'].pop('powerControlEnabled')
        registry.devices['plug'].pop('connectedLoad')
        self.assertFalse(registry.read('plug')['canSetOutput'])
        with self.assertRaises(ValueError):registry.set_output('plug',True)
        registry.devices['plug']['powerControlEnabled']=True
        with self.assertRaises(ValueError):registry.set_output('plug',True)
        registry.devices['plug']['connectedLoad']='Fixture lamp'
        self.assertTrue(registry.read('plug')['canSetOutput'])

    def test_busy_device_rejects_write_without_waiting_or_dispatch(self):
        registry=self.fixture();registry.locks['plug'].acquire()
        try:
            with self.assertRaises(self.module.DeviceBusy):registry.set_output('plug',True)
            token='fixture-operator-secret-token'
            status,body,_=self.http_request(registry,token=token,supplied=token,
                method='POST',path='/v1/devices/plug/output',body={'on':True})
            self.assertEqual(status,409)
            self.assertIn('no power request dispatched',body['error'])
        finally:registry.locks['plug'].release()
        self.assertNotIn(('write',True),self.calls)

    def test_status_cache_and_expiry(self):
        registry=self.fixture()
        self.assertEqual(registry.read('plug')['output'],False)
        registry.read('plug');self.assertEqual(self.calls,['read'])
        self.now=3;registry.read('plug');self.assertEqual(self.calls,['read','read'])

    def test_read_failure_marks_unknown_instead_of_off(self):
        registry=self.fixture();registry.read('plug');self.adapter.fail=True;self.now=3
        row=registry.read('plug');self.assertIsNone(row['output']);self.assertTrue(row['stale'])
        self.assertEqual(row['state'],'unavailable')

    def test_explicit_write_updates_observed_cache(self):
        registry=self.fixture();r=registry.set_output('plug',True)
        self.assertTrue(r['confirmed']);self.assertEqual(registry.read('plug')['output'],True)
        self.assertEqual(self.calls,[('write',True)])

    def test_unknown_write_is_not_retried_or_reported_as_off(self):
        registry=self.fixture();self.adapter.fail=True
        with self.assertRaises(self.module.UnknownOutcome):registry.set_output('plug',True)
        self.assertEqual(self.calls,[('write',True)])
        self.assertIsNone(registry.read('plug')['output'])

    def test_disabled_or_omada_write_rejected(self):
        registry=self.module.DeviceRegistry(json.loads((DIRECTORY/'inventory.json').read_text()))
        for name in ['shelly-plug-1','fill-poe-1']:
            with self.assertRaises(ValueError):registry.set_output(name,True)

    def test_duplicate_ids_rejected(self):
        value={'id':'duplicate','kind':'shelly','enabled':False,'address':None}
        with self.assertRaises(ValueError):self.module.DeviceRegistry({'schemaVersion':1,'devices':[value,value]})

    def http_request(self, registry, *, token=None, supplied=None, body=None, method='GET', path='/v1/devices', monitor=None):
        import threading,urllib.request,urllib.error
        from http.server import ThreadingHTTPServer
        server=ThreadingHTTPServer(('127.0.0.1',0),self.module.handler_for(registry,operator_token=token,wan_monitor=monitor))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            headers={'Content-Type':'application/json'}
            if supplied is not None:headers['Authorization']='Bearer '+supplied
            request=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,
                data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
            try:response=urllib.request.urlopen(request,timeout=3)
            except urllib.error.HTTPError as error:response=error
            with response:return response.status,json.loads(response.read()),dict(response.headers)
        finally:server.shutdown();server.server_close();thread.join()

    def test_wan_endpoint_is_cached_and_default_disabled(self):
        registry=self.fixture()
        status,body,_=self.http_request(registry,path='/v1/wan')
        self.assertEqual(status,200);self.assertEqual(body['state'],'disabled')
        class Monitor:
            def snapshot(self):return {'enabled':True,'state':'pending'}
        status,body,_=self.http_request(registry,path='/v1/wan',monitor=Monitor())
        self.assertEqual(body['state'],'pending');self.assertEqual(self.calls,[])

    def test_http_get_exposes_no_credentials_and_is_not_cached(self):
        registry=self.fixture()
        status,body,headers=self.http_request(registry,token='fixture-operator-secret-token')
        self.assertEqual(status,200);self.assertEqual(body['devices'][0]['output'],False)
        self.assertNotIn('fixture-operator-secret-token',json.dumps(body))
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertNotIn('Access-Control-Allow-Origin',headers)

    def test_http_rejects_missing_wrong_or_non_ascii_authorization_without_write(self):
        registry=self.fixture()
        for supplied in [None,'wrong','invalid-ÿ']:
            status,_,_=self.http_request(registry,token='fixture-operator-secret-token',supplied=supplied,
                                        method='POST',path='/v1/devices/plug/output',body={'on':True})
            self.assertEqual(status,403)
        self.assertEqual(self.calls,[])

    def test_http_authenticated_write_and_unknown_outcome(self):
        registry=self.fixture();token='fixture-operator-secret-token'
        status,body,_=self.http_request(registry,token=token,supplied=token,
            method='POST',path='/v1/devices/plug/output',body={'on':True})
        self.assertEqual(status,200);self.assertTrue(body['confirmed'])
        self.adapter.fail=True
        status,body,_=self.http_request(registry,token=token,supplied=token,
            method='POST',path='/v1/devices/plug/output',body={'on':False})
        self.assertEqual(status,503);self.assertEqual(body['outcome'],'unknown')
        self.assertEqual(self.calls,[('write',True),('write',False)])

    def test_http_without_configured_token_has_no_power_writes(self):
        registry=self.fixture()
        status,_,_=self.http_request(registry,supplied='anything',method='POST',path='/v1/devices/plug/output',body={'on':True})
        self.assertEqual(status,403);self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main()
