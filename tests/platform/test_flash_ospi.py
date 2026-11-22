"""Exercise the real flashing script against a fake SSH endpoint; no board access."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class FlashPreflight(unittest.TestCase):
    def run_fixture(self, status, **overrides):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)
            image = p / 'image'; image.mkdir()
            data = b'fixture FIT, not firmware\n'
            (image / 'fitImage.itb').write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            (image / 'SHA256SUMS').write_text(digest + '  fitImage.itb\n')
            (image / 'partitions').write_text('fitImage.itb ospi.rootfs\n')
            ssh = p / 'ssh'
            ssh.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
with open(os.environ['SSH_LOG'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
cmd=sys.argv[-1]
if 'command -v flashcp' in cmd:
 status=int(os.environ['SSH_STATUS'])
 if status==255: print('Permission denied (publickey).',file=sys.stderr)
 sys.exit(status)
if '/proc/mtd' in cmd: print(os.environ.get('REMOTE_MTD','mtd5'))
elif '/size' in cmd: print(os.environ.get('REMOTE_SIZE','4096'))
elif 'cat >' in cmd: Path(os.environ['SSH_STAGE']).write_bytes(sys.stdin.buffer.read())
elif 'sha256sum' in cmd:
 import hashlib
 print(hashlib.sha256(Path(os.environ['SSH_STAGE']).read_bytes()).hexdigest())
elif 'flashcp -v' in cmd: print('read-back verified (fixture)')
else: sys.exit(19)
''')
            ssh.chmod(0o755)
            env = {**os.environ, 'PATH':str(p)+os.pathsep+os.environ['PATH'],
                   'SSH_LOG':str(p/'calls'), 'SSH_STAGE':str(p/'staged'), 'SSH_STATUS':str(status), **overrides}
            result = subprocess.run(['bash', str(ROOT/'tools/flash-ospi.sh'), 'fillstation-deploy', 'fit', str(image)],
                                    text=True, capture_output=True, env=env, timeout=5)
            calls = [json.loads(x) for x in (p/'calls').read_text().splitlines()]
            return result,calls

    def test_auth_failure_is_not_reported_as_missing_flashcp(self):
        r,calls=self.run_fixture(255)
        self.assertNotEqual(r.returncode,0)
        self.assertIn('SSH preflight failed',r.stderr)
        self.assertNotIn("flashcp isn't on the board",r.stderr)
        self.assertEqual(len(calls),1)

    def test_explicit_remote_missing_tool(self):
        r,calls=self.run_fixture(42)
        self.assertNotEqual(r.returncode,0)
        self.assertIn("flashcp isn't on the board",r.stderr)
        self.assertEqual(len(calls),1)

    def test_other_remote_failure_is_not_missing_tool(self):
        r,calls=self.run_fixture(17)
        self.assertNotEqual(r.returncode,0)
        self.assertNotIn("flashcp isn't on the board",r.stderr)
        self.assertEqual(len(calls),1)

    def test_malformed_partition_or_capacity_never_stages_or_writes(self):
        for env in [{'REMOTE_MTD':'mtd5;bad'}, {'REMOTE_MTD':'mtd5\nmtd6'}, {'REMOTE_SIZE':'not-a-size'}]:
            with self.subTest(env=env):
                result,calls=self.run_fixture(0,**env)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(any('cat >' in c[-1] or 'flashcp -v' in c[-1] for c in calls))

    def test_fit_transfer_checksum_and_readback_use_bounded_strict_ssh(self):
        r,calls=self.run_fixture(0)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('Flash updated and verified',r.stdout)
        self.assertTrue(any('flashcp -v' in call[-1] for call in calls))
        for call in calls:
            self.assertIn('StrictHostKeyChecking=yes',call)
            self.assertIn('ConnectTimeout=5',call)
            self.assertIn('BatchMode=yes',call)
        self.assertFalse(any('reboot' in call[-1] for call in calls))

if __name__ == '__main__': unittest.main()
