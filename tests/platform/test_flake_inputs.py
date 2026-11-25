"""Locked source inventory uses local hashing/metadata, never flake fetching."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.platform import flake_inputs as flakes
from tools.platform.runtime import PlatformError
SRC='/nix/store/'+'d'*32+'-source'
HASH='sha256-'+('A'*43)+'='
def lock():return {'version':7,'root':'root','nodes':{'root':{'inputs':{'dep':'dep'}},'dep':{'locked':{'type':'github','owner':'fixture','repo':'dep','rev':'a'*40,'narHash':HASH}}}}
class FlakeInputs(unittest.TestCase):
 def fixture(self,d):
  path=Path(d)/'flake.lock';path.write_text(json.dumps(lock()));return path
 def test_inspection_computes_paths_without_fetching_or_pinning(self):
  calls=[]
  def run(args,**kwargs):
   calls.append(args);return SRC if '--print-fixed-path' in args else ''
  with tempfile.TemporaryDirectory() as d,patch.object(flakes,'run',side_effect=run),patch.object(flakes.os.path,'lexists',return_value=True):
   result=flakes.execute(self.fixture(d),Path(d)/'state')
   self.assertEqual(result['assessment'],'locked_sources_present');self.assertIsNone(result['pin'])
   self.assertFalse((Path(d)/'state').exists())
  self.assertTrue(all('fetch' not in args and 'archive' not in args and 'build' not in args for args in calls))
 def test_missing_source_prevents_pin(self):
  with tempfile.TemporaryDirectory() as d,patch.object(flakes,'run',return_value=SRC),patch.object(flakes.os.path,'lexists',return_value=False),patch.object(flakes.offline_pins,'execute',side_effect=AssertionError('pin')):
   result=flakes.execute(self.fixture(d),Path(d)/'state',pin=True)
  self.assertEqual(result['assessment'],'missing_locked_sources');self.assertFalse(result['retained'])
 def test_unknown_types_are_not_silently_covered(self):
  data=lock();data['nodes']['dep']['locked']['type']='path'
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'flake.lock';path.write_text(json.dumps(data))
   with patch.object(flakes,'run',side_effect=AssertionError('network')):result=flakes.execute(path,Path(d)/'state')
  self.assertEqual(result['assessment'],'unsupported_inputs');self.assertTrue(result['unsupportedInputs'])
 def test_registration_failure_is_unverifiable(self):
  with tempfile.TemporaryDirectory() as d,patch.object(flakes,'run',side_effect=[SRC,PlatformError('daemon')]),patch.object(flakes.os.path,'lexists',return_value=True):
   result=flakes.execute(self.fixture(d),Path(d)/'state',pin=True)
  self.assertEqual(result['assessment'],'unverifiable');self.assertFalse(result['retained'])
 def test_invalid_lock_or_hash_rejected(self):
  for data in [{'version':99,'root':'root','nodes':{}},{**lock(),'nodes':{'root':{},'dep':{'locked':{'type':'github','rev':'a'*40,'narHash':'sha256-bad'}}}}]:
   with tempfile.TemporaryDirectory() as d:
    path=Path(d)/'flake.lock';path.write_text(json.dumps(data))
    with self.assertRaises(PlatformError):flakes.execute(path,Path(d)/'state')
 def test_changed_lock_aborts_before_pinning(self):
  with tempfile.TemporaryDirectory() as d:
   path=self.fixture(d)
   def run(args,**kwargs):
    if '--print-fixed-path' in args:return SRC
    path.write_text('{}');return ''
   with patch.object(flakes,'run',side_effect=run),patch.object(flakes.os.path,'lexists',return_value=True),patch.object(flakes.offline_pins,'execute',side_effect=AssertionError('pin')):
    with self.assertRaisesRegex(PlatformError,'changed'):flakes.execute(path,Path(d)/'state',pin=True)
 def test_present_sources_can_be_pinned_with_digest_descriptor(self):
  with tempfile.TemporaryDirectory() as d:
   path=self.fixture(d);root=Path(d)/'pin/root';root.parent.mkdir()
   def run(args,**kwargs):
    if '--print-fixed-path' in args:return SRC
    if args[0]=='nix-instantiate':return '/nix/store/'+'a'*32+'-metadata.drv'
    return ''
   with patch.object(flakes,'run',side_effect=run),patch.object(flakes.os.path,'lexists',return_value=True),patch.object(flakes.offline_pins,'execute',return_value={'retained':True,'root':str(root)}):
    result=flakes.execute(path,Path(d)/'state',pin=True)
   self.assertTrue(result['retained']);self.assertFalse(result['offlineEvaluationValidated'])
   descriptor=json.loads((root.parent/'flake-inputs.json').read_text())
   self.assertEqual(descriptor['lockSha256'],result['lockSha256'])
 def test_broken_direct_and_follows_references_and_null_root_fail(self):
  invalid=[]
  data=lock();data['nodes']['root']=None;invalid.append(data)
  data=lock();data['nodes']['root']['inputs']['dep']='absent';invalid.append(data)
  data=lock();data['nodes']['root']['inputs']['dep']=['absent'];invalid.append(data)
  data=lock();data['nodes']['root']['inputs']['dep']=['dep'];invalid.append(data)
  for data in invalid:
   with tempfile.TemporaryDirectory() as d:
    path=Path(d)/'flake.lock';path.write_text(json.dumps(data))
    with patch.object(flakes,'run',side_effect=AssertionError('Nix before validation')):
     with self.assertRaises(PlatformError):flakes.execute(path,Path(d)/'state',pin=True)
 def test_cli_inspection_does_not_read_unrelated_config(self):
  from tools.platform import cli
  import contextlib,io
  with tempfile.TemporaryDirectory() as d,patch.object(cli,'state_directory',return_value=Path(d)),patch.object(cli,'load_config',side_effect=AssertionError('unrelated config')),patch.object(flakes,'execute',return_value={'assessment':'locked_sources_present'}),contextlib.redirect_stdout(io.StringIO()):
   self.assertEqual(cli.main(['flake-inputs','--lock-file',str(Path(d)/'flake.lock')]),0)
