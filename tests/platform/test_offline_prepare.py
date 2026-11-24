"""Cache-only missing-input preparation; fake Nix never compiles or contacts devices."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.platform import offline_prepare as prep
from tools.platform.runtime import PlatformError
DRV='/nix/store/'+'c'*32+'-target.drv';SRC='/nix/store/'+'d'*32+'-source'
KEY='fixture:'+('A'*43)+'='
URL='http://192.168.1.206:8080/cache/'
def audit(missing=True):
 return {'assessment':'missing_static_inputs' if missing else 'static_inputs_present',
  'missingPaths':[SRC] if missing else [],'unverifiedPaths':[],
  'inventory':{'unresolvedOutputs':[]},'offlineBuildValidated':False}
class OfflinePrepare(unittest.TestCase):
 def test_preview_does_not_copy_or_pin(self):
  with patch.object(prep.offline_audit,'execute',return_value=audit()),patch.object(prep,'run',side_effect=AssertionError('copy')),patch.object(prep.offline_pins,'execute',side_effect=AssertionError('pin')):
   result=prep.execute(Path('/unused'),DRV,URL,KEY,dry_run=True,pin=True)
  self.assertFalse(result['prepared']);self.assertFalse(result['copied']);self.assertEqual(result['plannedPaths'],[SRC])
 def test_copy_is_explicit_signature_checked_and_never_builds(self):
  with patch.object(prep.offline_audit,'execute',side_effect=[audit(),audit(False)]),patch.object(prep,'run',return_value='') as run,patch.object(prep.offline_pins,'execute',return_value={'retained':True}) as pin:
   result=prep.execute(Path('/unused'),DRV,URL,KEY,pin=True)
  args=run.call_args.args[0]
  self.assertIn('copy',args);self.assertIn(URL,args);self.assertIn('require-sigs',args);self.assertIn(KEY,args)
  self.assertNotIn('build',args);self.assertNotIn('--realise',args);self.assertNotIn('--no-check-sigs',args)
  self.assertTrue(result['prepared']);self.assertFalse(result['offlineBuildValidated']);pin.assert_called_once()
 def test_failed_copy_does_not_pin_or_claim_prepared(self):
  with patch.object(prep.offline_audit,'execute',side_effect=[audit(),audit()]),patch.object(prep,'run',side_effect=PlatformError('cache missing')),patch.object(prep.offline_pins,'execute',side_effect=AssertionError('pin')):
   result=prep.execute(Path('/unused'),DRV,URL,KEY,pin=True)
  self.assertFalse(result['prepared']);self.assertEqual(result['remainingMissingPaths'],[SRC]);self.assertTrue(result['copyFailed'])
 def test_bad_cache_or_unknown_inventory_never_copies(self):
  for url,key in [('http://user:secret@example.org/',KEY),(URL,'not-a-key')]:
   with patch.object(prep,'run',side_effect=AssertionError('copy')),self.assertRaises(PlatformError):prep.execute(Path('/unused'),DRV,url,key)
  report=audit();report['unverifiedPaths']=[SRC];report['assessment']='unverifiable'
  with patch.object(prep.offline_audit,'execute',return_value=report),patch.object(prep,'run',side_effect=AssertionError('copy')),self.assertRaises(PlatformError):prep.execute(Path('/unused'),DRV,URL,KEY)
 def test_missing_derivation_is_not_treated_as_build_installable(self):
  report=audit();report['missingPaths']=[DRV]
  with patch.object(prep.offline_audit,'execute',return_value=report),self.assertRaises(PlatformError):prep.execute(Path('/unused'),DRV,URL,KEY)
 def test_already_present_inputs_need_no_cache_request(self):
  with patch.object(prep.offline_audit,'execute',return_value=audit(False)),patch.object(prep,'run',side_effect=AssertionError('copy')):
   result=prep.execute(Path('/unused'),DRV,URL,KEY)
  self.assertTrue(result['prepared']);self.assertFalse(result['copyAttempted'])
 def test_cli_partial_result_is_nonzero(self):
  from tools.platform import cli
  import contextlib,io,tempfile
  with tempfile.TemporaryDirectory() as d,patch.object(cli,'state_directory',return_value=Path(d)),patch.object(prep,'execute',return_value={'prepared':False}),contextlib.redirect_stdout(io.StringIO()):
   self.assertEqual(cli.main(['offline-prepare','--drv',DRV,'--cache-url',URL,'--public-key',KEY]),2)
