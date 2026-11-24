"""Read-only fixed-inventory management inspection; no actual LAN devices."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('omada_inspection',ROOT/'ground-station/network-devices/inspect_omada.py')
inspection=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspection)

class InspectionTests(unittest.TestCase):
    def inventory(self,address='192.168.1.100'):
        return {'schemaVersion':1,'devices':[
            {'id':'switch','kind':'omada-switch','address':address,'model':'ES205GP'},
            {'id':'plug','kind':'shelly','address':None}]}
    def test_default_is_plan_without_network(self):
        with patch.object(inspection,'probe_endpoint',side_effect=AssertionError('network')):
            report=inspection.inspect(self.inventory())
        self.assertFalse(report['probed'])
        self.assertEqual(report['devices'][0]['endpoints'],['http://192.168.1.100/','https://192.168.1.100/'])
        self.assertEqual(len(report['devices']),1)
    def test_rejects_external_or_malformed_inventory_before_any_probe(self):
        for address in ['8.8.8.8','127.0.0.1','169.254.1.2','192.168.1.100/path','host.local',None]:
            with self.subTest(address=address),patch.object(inspection,'probe_endpoint',side_effect=AssertionError('network')):
                with self.assertRaises(ValueError):inspection.inspect(self.inventory(address),probe=True)
    def test_probe_errors_are_unavailable_not_off_or_unreachable_certainty(self):
        with patch.object(inspection,'probe_endpoint',return_value={'state':'unavailable','error':'timeout'}):
            report=inspection.inspect(self.inventory(),probe=True)
        self.assertTrue(report['probed'])
        self.assertEqual(len(report['devices'][0]['observations']),2)
        self.assertNotIn('output',json.dumps(report))
    def test_root_get_discards_redirect_headers_and_credentials(self):
        class Wire:
            def __init__(self):self.sent=b'';self.closed=False
            def settimeout(self,value):pass
            def sendall(self,data):self.sent=data
            def recv(self,size):return b'HTTP/1.1 302 Found\r\nLocation: http://8.8.8.8/private\r\nSet-Cookie: private-token\r\n\r\nprivate-body'
            def close(self):self.closed=True
        wire=Wire()
        result=inspection.probe_endpoint('192.168.1.100','http',socket_factory=lambda *args:wire)
        self.assertEqual(result,{'state':'http_response','status':302,'redirect':True})
        self.assertTrue(wire.sent.startswith(b'GET / HTTP/1.1\r\n'))
        self.assertNotIn(b'Authorization',wire.sent)
        self.assertTrue(wire.closed)
        self.assertNotIn('private',json.dumps(result))
    def test_oversized_headers_are_bounded(self):
        class Wire:
            def settimeout(self,value):pass
            def sendall(self,data):pass
            def recv(self,size):return b'x'*size
            def close(self):pass
        result=inspection.probe_endpoint('192.168.1.100','http',socket_factory=lambda *args:Wire())
        self.assertEqual(result['error'],'connection_or_protocol_error')
    def test_one_deadline_covers_full_exchange(self):
        class Wire:
            def settimeout(self,value):pass
            def sendall(self,data):pass
            def close(self):pass
        with patch.object(inspection.time,'monotonic',side_effect=[0,0.1,3]):
            result=inspection.probe_endpoint('192.168.1.100','http',socket_factory=lambda *args:Wire())
        self.assertEqual(result['error'],'timeout')
    def test_tls_fingerprint_is_explicitly_unverified(self):
        class Wire:
            def settimeout(self,value):pass
            def sendall(self,data):pass
            def recv(self,size):return b'HTTP/1.1 200 OK\r\n\r\n'
            def getpeercert(self,*,binary_form):return b'fixture certificate'
            def close(self):pass
        class Context:
            def wrap_socket(self,wire,*,server_hostname):return wire
        with patch.object(inspection.ssl,'SSLContext',return_value=Context()):
            result=inspection.probe_endpoint('192.168.1.100','https',socket_factory=lambda *args:Wire())
        self.assertEqual(result['certificateSha256'],inspection.hashlib.sha256(b'fixture certificate').hexdigest())
        self.assertFalse(result['certificateVerified'])
    def test_socket_exchange_against_loopback_fixture(self):
        import socket,threading
        listener=socket.socket()
        listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(3)
        requests=[]
        def serve():
            with listener:
                peer,_=listener.accept()
                with peer:
                    peer.settimeout(3);requests.append(peer.recv(4096))
                    peer.sendall(b'HTTP/1.1 401 Unauthorized\r\nSet-Cookie: private\r\nContent-Length: 0\r\n\r\n')
        endpoint=listener.getsockname()
        worker=threading.Thread(target=serve,daemon=True);worker.start()
        result=inspection.probe_endpoint('192.168.1.100','http',socket_factory=lambda addr,timeout:socket.create_connection(endpoint,timeout))
        worker.join(4)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result,{'state':'http_response','status':401,'redirect':False})
        self.assertEqual(len(requests),1)
        self.assertNotIn('private',json.dumps(result))
    def test_real_inventory_has_only_five_inspection_targets(self):
        report=inspection.inspect(json.loads((ROOT/'ground-station/network-devices/inventory.json').read_text()))
        self.assertEqual(len(report['devices']),5)
        self.assertFalse(report['authenticated'])

if __name__=='__main__':unittest.main()
