"""Exercise the Python demo mock without opening any network listeners."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]

class SolenoidQDClient(unittest.TestCase):
 def test_dashboard_has_no_motor_requests_or_motor_position_controls(self):
  s=(ROOT/'fill-station/client/dashboard_v2.py').read_text()
  for old in ['"qd_move"','"qd_retract"','"qd_extend"','"get_qd_state"','self.qd_state','QD Stepper','Manual Steps']:
   self.assertNotIn(old,s)
  self.assertIn('Hybrid QD',s)
 def test_mock_accepts_generic_sv5_release_and_rejects_removed_motor_api(self):
  spec=importlib.util.spec_from_file_location('qd_mock_server',ROOT/'fill-station/client/mock_server.py')
  mod=importlib.util.module_from_spec(spec)
  stub=types.SimpleNamespace(exceptions=types.SimpleNamespace(ConnectionClosed=type('Closed',(Exception,),{})))
  with patch.dict(sys.modules,{'websockets':stub}):spec.loader.exec_module(mod)
  messages=[{'command':'actuate_valve','valve':'SV5','open':True},
            {'command':'get_valve_state','valve':'SV5'},
            {'command':'actuate_valve','valve':'SV5','open':False},
            {'command':'get_valve_state','valve':'SV5'}]
  messages += [{'command':c,'steps':1,'direction':True} for c in ['qd_move','qd_retract','qd_extend','get_qd_state']]
  class Socket:
   remote_address=("fixture",0)
   responses=[]
   def __aiter__(self):return self
   async def __anext__(self):
    if not messages:raise StopAsyncIteration
    return json.dumps(messages.pop(0))
   async def send(self,value):self.responses.append(json.loads(value))
  socket=Socket();asyncio.run(mod.handler(socket))
  reports=[r for r in socket.responses if r.get('type')=='valve_state']
  self.assertEqual([r['open'] for r in reports],[True,False])
  self.assertEqual([r['type'] for r in socket.responses[-4:]],['error']*4)
  self.assertNotIn('qd',mod.state)

if __name__=='__main__':unittest.main()
