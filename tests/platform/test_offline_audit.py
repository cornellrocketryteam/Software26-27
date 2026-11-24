"""Static Nix metadata audit; injected fixtures never realize derivations."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.platform import offline_audit as audit
from tools.platform.runtime import PlatformError

def path(name):return '/nix/store/'+'a'*32+'-'+name
DRV=path('example.drv');SRC=path('source');FETCH=path('fetch')
def graph():return {DRV:{'inputSrcs':[SRC],'inputDrvs':{},'outputs':{'out':{'path':FETCH,'hash':'abc'}}}}
class OfflineAudit(unittest.TestCase):
    def test_legacy_and_version_four_are_normalized(self):
        old=audit.inputs(graph(),DRV)
        modern={'version':4,'derivations':{Path(DRV).name:{'inputs':{'srcs':[Path(SRC).name],'drvs':{}},'outputs':{'out':{'hash':'sha256-test','method':'flat'}},'env':{'out':FETCH}}}}
        self.assertEqual(audit.inputs(modern,DRV),old)
        self.assertIn(FETCH,old['fixedOutputs'])
    def test_unknown_schema_and_missing_derivation_fail(self):
        for payload in [{'version':99,'derivations':{}},{}, {DRV:{'other':1}}]:
            with self.assertRaises(PlatformError):audit.inputs(payload,DRV)
    def test_missing_inputs_do_not_compile_or_claim_ready(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            return json.dumps(graph()) if 'show' in args else ''
        with patch.object(audit,'run',side_effect=run),patch.object(audit.os.path,'lexists',side_effect=lambda p:p!=FETCH):
            result=audit.execute(DRV)
        self.assertEqual(result['assessment'],'missing_static_inputs')
        self.assertIn(FETCH,result['missingPaths'])
        self.assertFalse(result['offlineBuildValidated'])
        self.assertTrue(all('build' not in args and '--realise' not in args for args in calls))
    def test_present_static_inputs_are_not_offline_build_proof(self):
        with patch.object(audit,'run',side_effect=[json.dumps(graph()),'']),patch.object(audit.os.path,'lexists',return_value=True):
            result=audit.execute(DRV)
        self.assertEqual(result['assessment'],'static_inputs_present')
        self.assertFalse(result['offlineBuildValidated'])
    def test_registration_failure_is_unverifiable_not_missing(self):
        with patch.object(audit,'run',side_effect=[json.dumps(graph()),PlatformError('daemon unavailable')]),patch.object(audit.os.path,'lexists',return_value=True):
            result=audit.execute(DRV)
        self.assertEqual(result['assessment'],'unverifiable')
        self.assertEqual(result['missingPaths'],[])
        self.assertTrue(result['unverifiedPaths'])
    def test_incomplete_graph_and_malformed_dependency_fail_cleanly(self):
        data=graph();data[DRV]['inputDrvs']={path('absent.drv'):['out']}
        with self.assertRaises(PlatformError):audit.inputs(data,DRV)
        data=graph();data[path('bad.drv')]=[]
        with self.assertRaises(PlatformError):audit.inputs(data,DRV)
    def test_cli_report_exit_status_does_not_call_build(self):
        from tools.platform import cli
        import contextlib,io,tempfile
        with tempfile.TemporaryDirectory() as directory,patch.object(cli,'state_directory',return_value=Path(directory)),patch.object(cli.offline_audit,'execute',return_value={'assessment':'missing_static_inputs'}),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['offline-audit','--drv',DRV]),2)
        self.assertEqual(json.loads(output.getvalue())['assessment'],'missing_static_inputs')
    def test_per_record_modern_format_and_simple_dependency_list(self):
        child=path('child.drv')
        data={DRV:{'version':4,'inputs':{'srcs':[SRC],'drvs':{child:['out']}},'outputs':{'out':{'path':FETCH}}},
              child:{'version':4,'inputs':{'srcs':[],'drvs':{}},'outputs':{'out':{'path':path('child')}}}}
        self.assertIn(SRC,audit.inputs(data,DRV)['sources'])
    def test_output_limit_is_enforced_while_child_runs(self):
        with self.assertRaisesRegex(PlatformError,'output limit'):
            audit.bounded_run([sys.executable,'-c',"import sys,time;sys.stdout.write('x'*4096);sys.stdout.flush();time.sleep(30)"],timeout=3,output_limit=128)
    def test_expired_filesystem_phase_fails_instead_of_missing_report(self):
        with patch.object(audit,'run',return_value=json.dumps(graph())),patch.object(audit.time,'monotonic',side_effect=[0,999]):
            with self.assertRaisesRegex(PlatformError,'budget'):audit.execute(DRV,1)
    def test_unsupported_record_version_in_envelope_is_rejected(self):
        data={'version':4,'derivations':{Path(DRV).name:{'version':99,'inputs':{'srcs':[],'drvs':{}},'outputs':{'out':{'path':FETCH}}}}}
        with self.assertRaises(PlatformError):audit.inputs(data,DRV)
    def test_invalid_time_budget_never_runs_nix(self):
        with patch.object(audit,'run',side_effect=AssertionError('subprocess')):
            for timeout in [0,301,True]:
                with self.assertRaises(PlatformError):audit.execute(DRV,timeout)
    def test_dynamic_or_unknown_output_never_passes(self):
        data=graph();data[DRV]['outputs']={'out':{}}
        result=audit.inputs(data,DRV)
        self.assertTrue(result['unresolvedOutputs'])
        with self.assertRaises(PlatformError):audit.execute('/tmp/untrusted.drv')
