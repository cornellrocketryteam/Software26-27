"""WAN monitoring with injected probes/clocks; no actual public endpoint calls."""
import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('wan',ROOT/'ground-station/network-devices/wan.py')
wan=importlib.util.module_from_spec(spec);spec.loader.exec_module(wan)
CONFIG={'targets':[{'label':'Fixture external service','address':'1.1.1.1','port':443}],'intervalSeconds':10,'timeoutSeconds':1}
class WanTests(unittest.TestCase):
 def fixture(self):
  self.now=0;self.reachable=True
  def probe(*args):return {'reachable':self.reachable,'connectMs':12.5 if self.reachable else None}
  self.monitor=wan.WanMonitor(CONFIG,probe=probe,clock=lambda:self.now,wall=lambda:1000)
  return self.monitor
 def test_configuration_is_explicit_and_public_only(self):
  for config in [{},{**CONFIG,'targets':[]},{**CONFIG,'targets':[{'label':'bad','address':'127.0.0.1','port':443}]},{**CONFIG,'intervalSeconds':0},{**CONFIG,'timeoutSeconds':99}]:
   with self.assertRaises(ValueError):wan.WanMonitor(config)
  self.assertEqual(self.fixture().snapshot()['state'],'pending')
 def test_success_failure_recovery_and_stale_are_distinct(self):
  monitor=self.fixture();monitor.tick();report=monitor.snapshot()
  self.assertEqual(report['state'],'reachable');self.assertEqual(report['targets'][0]['connectMs'],12.5)
  self.reachable=False;self.now=10;monitor.tick();self.now=20;monitor.tick()
  report=monitor.snapshot();self.assertEqual(report['state'],'unreachable');self.assertEqual(report['observedFailureSpanSeconds'],10)
  self.assertAlmostEqual(report['targets'][0]['failureFraction'],2/3)
  self.now=100;self.assertEqual(monitor.snapshot()['state'],'stale')
  self.assertIsNone(monitor.snapshot()['observedFailureSpanSeconds'])
  self.reachable=True;monitor.tick();self.assertEqual(monitor.snapshot()['state'],'reachable')
 def test_window_is_bounded_and_snapshot_does_not_probe(self):
  monitor=self.fixture()
  for i in range(100):self.now=i*10;monitor.tick()
  self.assertEqual(monitor.snapshot()['targets'][0]['attempts'],30)
  self.monitor.probe=lambda *args: (_ for _ in ()).throw(AssertionError('snapshot network'))
  self.assertEqual(monitor.snapshot()['state'],'reachable')
 def test_disabled_has_no_target_or_connection_claim(self):
  report=wan.disabled_status();self.assertFalse(report['enabled']);self.assertEqual(report['state'],'disabled')
  self.assertEqual(report['targets'],[])
 def test_tcp_probe_loopback_and_connection_refusal(self):
  import socket
  from unittest.mock import patch
  with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
   listener.bind(('127.0.0.1',0));listener.listen(1)
   result=wan.tcp_probe('127.0.0.1',listener.getsockname()[1],0.5)
   self.assertTrue(result['reachable']);self.assertGreaterEqual(result['connectMs'],0)
  with patch.object(wan.socket,'socket',side_effect=ConnectionRefusedError):
   self.assertEqual(wan.tcp_probe('1.1.1.1',443,1),{'reachable':False,'connectMs':None})

 def test_check_config_does_not_start_monitor(self):
  import sys,tempfile,json,contextlib,io
  from unittest.mock import patch
  directory=ROOT/'ground-station/network-devices';sys.path.insert(0,str(directory))
  spec=importlib.util.spec_from_file_location('wan_service_check',directory/'service.py')
  service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)
  with tempfile.TemporaryDirectory() as d:
   config=Path(d)/'wan.json';config.write_text(json.dumps(CONFIG))
   with patch.object(service.WanMonitor,'start',side_effect=AssertionError('network')),contextlib.redirect_stdout(io.StringIO()):
    self.assertEqual(service.main(['--inventory',str(directory/'inventory.json'),'--wan-config',str(config),'--check-config']),0)
