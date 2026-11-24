"""Metadata-only input retention; fake Nix never builds or fetches."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.platform import offline_pins as pins
from tools.platform.runtime import PlatformError

def path(name):return '/nix/store/'+'b'*32+'-'+name
DRV=path('build.drv');SRC=path('source');META=path('crt-offline-input-pin.drv')
def report(assessment='static_inputs_present'):
 return {'assessment':assessment,'inventory':{'sources':[SRC],'derivations':[DRV],'fixedOutputs':[],'unresolvedOutputs':[]},'offlineBuildValidated':False}
class OfflinePins(unittest.TestCase):
 def test_dry_run_audits_but_does_not_create_state(self):
  with tempfile.TemporaryDirectory() as d,patch.object(pins.offline_audit,'execute',return_value=report()),patch.object(pins,'run',side_effect=AssertionError('mutation')):
   state=Path(d)/'new-state';result=pins.execute(state,DRV,dry_run=True)
   self.assertFalse(state.exists());self.assertFalse(result['retained']);self.assertEqual(result['pathCount'],2)
 def test_missing_audit_never_starts_retention(self):
  with tempfile.TemporaryDirectory() as d,patch.object(pins.offline_audit,'execute',return_value=report('missing_static_inputs')):
   with self.assertRaises(PlatformError):pins.execute(Path(d),DRV)
   self.assertEqual(list(Path(d).iterdir()),[])
 def test_registered_root_and_all_input_refs_required_before_receipt(self):
  calls=[]
  def run(args,**kwargs):
   calls.append(args)
   if args[0]=='nix-instantiate':
    root=Path(args[args.index('--add-root')+1]);root.symlink_to(META);return META+'\n'
   if '--requisites' in args:return '\n'.join([META,DRV,SRC])
   return str(root_path())+' -> '+META+'\n'
  def root_path():return next((state/'offline-input-pins').glob('*/root'))
  with tempfile.TemporaryDirectory() as d,patch.object(pins.offline_audit,'execute',return_value=report()),patch.object(pins,'run',side_effect=run):
   state=Path(d).resolve();result=pins.execute(state,DRV)
   self.assertTrue(result['retained']);self.assertFalse(result['offlineBuildValidated'])
   receipt=json.loads(next((state/'offline-input-pins').glob('*/receipt.json')).read_text())
   self.assertEqual(receipt['retainedPathCount'],2)
   expression=next((state/'offline-input-pins').glob('*/pin.nix')).read_text()
   self.assertIn('map builtins.storePath',expression);self.assertNotIn('", "',expression)
   self.assertTrue(all('--realise' not in args and 'build' not in args for args in calls))
 def test_failed_instantiation_keeps_partial_record_without_success_receipt(self):
  with tempfile.TemporaryDirectory() as d,patch.object(pins.offline_audit,'execute',return_value=report()),patch.object(pins,'run',side_effect=PlatformError('failed')):
   with self.assertRaises(PlatformError):pins.execute(Path(d),DRV)
   self.assertEqual(len(list((Path(d)/'offline-input-pins').glob('*/audit.json'))),1)
   self.assertEqual(list((Path(d)/'offline-input-pins').glob('*/receipt.json')),[])

 def test_unregistered_root_never_gets_success_receipt(self):
  def run(args,**kwargs):
   if args[0]=='nix-instantiate':Path(args[args.index('--add-root')+1]).symlink_to(META);return META
   if '--requisites' in args:return '\n'.join([META,DRV,SRC])
   return '/some/other/root -> '+META
  with tempfile.TemporaryDirectory() as d,patch.object(pins.offline_audit,'execute',return_value=report()),patch.object(pins,'run',side_effect=run):
   with self.assertRaises(PlatformError):pins.execute(Path(d),DRV)
   self.assertEqual(pins.status(Path(d))[0]['state'],'partial')
 def test_symlinked_pin_directory_rejected(self):
  with tempfile.TemporaryDirectory() as d,patch.object(pins.offline_audit,'execute',return_value=report()):
   state=Path(d);(state/'offline-input-pins').symlink_to(state/'elsewhere')
   with self.assertRaises(PlatformError):pins.execute(state,DRV)
 def test_capacity_never_evicts_existing_pins(self):
  with tempfile.TemporaryDirectory() as d,patch.object(pins.offline_audit,'execute',return_value=report()):
   base=Path(d)/'offline-input-pins';base.mkdir()
   for i in range(8):(base/str(i)).mkdir()
   with self.assertRaises(PlatformError):pins.execute(Path(d),DRV)
   self.assertEqual(len(list(base.iterdir())),8)

 def test_fifo_receipt_cannot_block_status(self):
  import os
  with tempfile.TemporaryDirectory() as d:
   directory=Path(d)/'offline-input-pins'/('c'*32);directory.mkdir(parents=True)
   os.mkfifo(directory/'receipt.json')
   import subprocess
   child=subprocess.run([sys.executable,'-c',
    'from pathlib import Path;from tools.platform.offline_pins import status;import sys;status(Path(sys.argv[1]))',d],
    cwd=ROOT,capture_output=True,text=True,timeout=2)
   self.assertNotEqual(child.returncode,0)
   self.assertIn('bounded regular file',child.stderr)
 def test_release_selected_partial_root_without_store_delete_or_gc(self):
  with tempfile.TemporaryDirectory() as d:
   state=Path(d).resolve();directory=state/'offline-input-pins'/('c'*32);directory.mkdir(parents=True)
   root=directory/'root';root.symlink_to(META)
   with patch.object(pins,'run',side_effect=AssertionError('no Nix mutation')):
    preview=pins.release(state,'c'*32,dry_run=True)
    self.assertTrue(root.is_symlink());self.assertFalse(preview['released'])
    result=pins.release(state,'c'*32)
   self.assertTrue(result['released']);self.assertFalse(root.is_symlink())
   self.assertFalse(directory.exists());self.assertTrue(Path(result['archiveDirectory']).is_dir())
   self.assertEqual(pins.status(state),[])
 def test_release_rejects_traversal_and_unexpected_root(self):
  with tempfile.TemporaryDirectory() as d:
   state=Path(d);directory=state/'offline-input-pins'/('c'*32);directory.mkdir(parents=True)
   (directory/'root').symlink_to(path('other.drv'))
   with self.assertRaises(PlatformError):pins.release(state,'../other')
   with self.assertRaises(PlatformError):pins.release(state,'c'*32)
   self.assertTrue((directory/'root').is_symlink())
