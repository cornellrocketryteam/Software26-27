"""Exercise deployment through the CLI and real flash script, with fake SSH only."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.platform.cli import main
from tools.platform.manifest import artifact_files

ROOT=Path(__file__).resolve().parents[2]
FAKE_SSH='''#!/usr/bin/env python3
import hashlib,json,os,sys
from pathlib import Path
with open(os.environ['SSH_LOG'],'a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')
if os.environ.get('SSH_FAIL'):
 print('Permission denied (publickey).',file=sys.stderr);sys.exit(255)
cmd=sys.argv[-1]
if 'command -v flashcp' in cmd:
 if os.environ.get('MUTATE_SOURCE'):Path(os.environ['MUTATE_SOURCE']).write_bytes(b'changed after staging')
elif '/proc/mtd' in cmd:print('mtd5')
elif '/size' in cmd:print('4096')
elif 'cat >' in cmd:Path(os.environ['SSH_STAGE']).write_bytes(sys.stdin.buffer.read())
elif 'sha256sum' in cmd:print(hashlib.sha256(Path(os.environ['SSH_STAGE']).read_bytes()).hexdigest())
elif 'flashcp -v' in cmd:
 if os.environ.get('FLASH_FAIL'):print('fixture write interrupted',file=sys.stderr);sys.exit(23)
 print('fixture read-back verified')
else:sys.exit(19)
'''

class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.image=self.root/'image';self.image.mkdir()
        self.names=['tiboot3.bin','tispl.bin','u-boot.img','fitImage.itb']
        for name in self.names:(self.image/name).write_bytes(('fixture '+name+'\n').encode())
        (self.image/'SHA256SUMS').write_text(''.join(hashlib.sha256((self.image/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in self.names))
        (self.image/'partitions').write_text('tiboot3.bin ospi.tiboot3\ntispl.bin ospi.tispl\nu-boot.img ospi.u-boot\nfitImage.itb ospi.rootfs\n')
        self.manifest=self.root/'manifest.json';self.refresh_manifest()
        ssh=self.root/'ssh';ssh.write_text(FAKE_SSH);ssh.chmod(0o755)
        self.state=self.root/'state'
        self.env={'PATH':str(self.root)+os.pathsep+os.environ['PATH'],'CRT_PLATFORM_STATE_DIR':str(self.state),
                  'SSH_LOG':str(self.root/'ssh-calls'),'SSH_STAGE':str(self.root/'board-staged')}

    def refresh_manifest(self):
        self.manifest.write_text(json.dumps({'schemaVersion':1,'releaseId':'fixture-release','host':'fill-station','vehicle':'hybrid',
            'artifacts':{'ospi':{'storePath':str(self.image),'files':artifact_files(self.image)}}}))

    def cli(self,*args,**env):
        out=io.StringIO();err=io.StringIO()
        with patch.dict(os.environ,{**self.env,**env}),redirect_stdout(out),redirect_stderr(err):
            code=main(list(args),repo=self.root)
        return code,out.getvalue(),err.getvalue()

    def deploy(self,*args,**env):
        return self.cli('deploy','--manifest',str(self.manifest),'--target','fillstation-deploy',*args,**env)

    def calls(self):
        p=self.root/'ssh-calls'
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def test_dry_run_verifies_manifest_without_ssh_or_state_writes(self):
        code,out,err=self.deploy('--dry-run');self.assertEqual(code,0,err)
        self.assertEqual(json.loads(out)['mode'],'fit');self.assertEqual(self.calls(),[])
        self.assertFalse(self.state.exists())

    def test_verified_fit_only_deployment_preserves_manifest_and_never_reboots(self):
        before=self.manifest.read_bytes()
        code,out,err=self.deploy();self.assertEqual(code,0,err)
        result=json.loads(out);self.assertEqual(result['state'],'flash-verified')
        self.assertFalse(result['rebootRequested']);self.assertEqual(self.manifest.read_bytes(),before)
        writes=[call[-1] for call in self.calls() if 'flashcp -v' in call[-1]]
        self.assertEqual(len(writes),1);self.assertIn('/dev/mtd5',writes[0])
        self.assertFalse(any('reboot' in call[-1] for call in self.calls()))
        record=json.loads(Path(result['record']).read_text());self.assertEqual(record['runtimeAcceptance'],'pending')
        code,out,err=self.cli('status');self.assertEqual(code,0,err)
        self.assertEqual(len(json.loads(out)['deployments']),1)

    def test_corrupt_fit_rejected_before_network_or_state(self):
        (self.image/'fitImage.itb').write_bytes(b'corrupt')
        code,_,_=self.deploy();self.assertNotEqual(code,0);self.assertEqual(self.calls(),[])
        self.assertFalse(self.state.exists())

    def test_bad_partition_mapping_rejected_even_with_matching_manifest_hashes(self):
        p=self.image/'partitions';p.write_text(p.read_text().replace('ospi.rootfs','ospi.env'))
        self.refresh_manifest();code,_,_=self.deploy();self.assertNotEqual(code,0)
        self.assertEqual(self.calls(),[]);self.assertFalse(self.state.exists())

    def test_auth_failure_records_unconfirmed_outcome_without_retry(self):
        code,_,err=self.deploy(SSH_FAIL='1');self.assertNotEqual(code,0)
        self.assertIn('Permission denied',err);self.assertEqual(len(self.calls()),1)
        records=list((self.state/'deployments').glob('*/*.json'));self.assertEqual(len(records),1)
        record=json.loads(records[0].read_text());self.assertEqual(record['state'],'failed')
        self.assertEqual(record['outcome'],'unconfirmed');self.assertFalse(record['rebootRequested'])

    def test_staged_bytes_are_independent_of_later_source_changes(self):
        original=(self.image/'fitImage.itb').read_bytes()
        code,_,err=self.deploy(MUTATE_SOURCE=str(self.image/'fitImage.itb'));self.assertEqual(code,0,err)
        self.assertEqual((self.root/'board-staged').read_bytes(),original)
        self.assertNotEqual((self.image/'fitImage.itb').read_bytes(),original)

    def test_empty_payload_rejected_even_with_matching_manifest_and_checksums(self):
        (self.image/'fitImage.itb').write_bytes(b'')
        (self.image/'SHA256SUMS').write_text(''.join(hashlib.sha256((self.image/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in self.names))
        self.refresh_manifest()
        code,_,_=self.deploy();self.assertNotEqual(code,0);self.assertEqual(self.calls(),[])
        self.assertFalse(self.state.exists())

    def test_interrupted_flash_is_not_retried_or_reported_as_verified(self):
        code,_,err=self.deploy(FLASH_FAIL='1');self.assertNotEqual(code,0)
        self.assertIn('write interrupted',err)
        self.assertEqual(len([c for c in self.calls() if 'flashcp -v' in c[-1]]),1)
        record=json.loads(next((self.state/'deployments').glob('*/*.json')).read_text())
        self.assertEqual((record['state'],record['outcome']),('failed','unconfirmed'))

    def test_installed_layout_uses_packaged_flash_script_outside_checkout(self):
        import shutil,subprocess,sys
        bundle=self.root/'installed'
        modules=bundle/'tools/platform';modules.mkdir(parents=True)
        for source in (ROOT/'tools/platform').glob('*.py'):shutil.copy(source,modules/source.name)
        (bundle/'tools/__init__.py').touch()
        shutil.copy(ROOT/'tools/flash-ospi.sh',bundle/'tools/flash-ospi.sh')
        command='import sys; sys.path.insert(0,sys.argv.pop(1)); from tools.platform.entry import main; raise SystemExit(main())'
        result=subprocess.run([sys.executable,'-I','-c',command,str(bundle),'deploy','--manifest',str(self.manifest),
            '--target','fillstation-deploy'],cwd=self.root,env={**os.environ,**self.env},text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['state'],'flash-verified')
        self.assertTrue(self.calls())

    def test_unsafe_target_rejected_before_network(self):
        code,_,_=self.cli('deploy','--manifest',str(self.manifest),'--target','root@host;bad')
        self.assertNotEqual(code,0);self.assertEqual(self.calls(),[])

if __name__=='__main__':unittest.main()
