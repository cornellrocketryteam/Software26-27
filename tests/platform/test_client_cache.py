import base64
import unittest
from tools.platform import client_cache
from tools.platform.runtime import PlatformError

KEY='station:'+base64.b64encode(bytes(range(32))).decode()
SETTINGS={'url':'http://192.168.1.206:8080/cache/','publicKey':KEY,
          'connectTimeoutSeconds':3,'stalledTimeoutSeconds':15}

class ClientCacheTests(unittest.TestCase):
    def test_adds_optional_cache_preserving_existing_settings(self):
        before='# existing\nextra-substituters = https://example.test/\ntrusted-users = root\n'
        result=client_cache.update(before,SETTINGS)
        self.assertTrue(result.startswith(before))
        self.assertIn('priority=20&retry-attempts=1',result)
        self.assertIn('extra-trusted-public-keys = '+KEY,result)
        self.assertIn('fallback = true',result)
        self.assertIn('require-sigs = true',result)
        self.assertEqual(result.count('trusted-users ='),1)
    def test_repeat_is_idempotent_and_updates_only_owned_block(self):
        first=client_cache.update('extra-trusted-public-keys = official:AAAA\n',SETTINGS)
        self.assertEqual(first,client_cache.update(first,SETTINGS))
        different=dict(SETTINGS,connectTimeoutSeconds=4)
        changed=client_cache.update(first,different)
        self.assertIn('connect-timeout = 4',changed)
        self.assertIn('official:AAAA',changed)
        self.assertNotIn('connect-timeout = 3',changed)
    def test_remove_restores_previous_text(self):
        original='# hello\ntrusted-users = root\n'
        self.assertEqual(client_cache.remove(client_cache.update(original,SETTINGS)),original)
    def test_rejects_unbalanced_or_duplicate_blocks(self):
        for text in [client_cache.BEGIN+'\n',client_cache.END+'\n',
                     client_cache.BEGIN+'\n'+client_cache.BEGIN+'\n'+client_cache.END+'\n']:
            with self.assertRaises(PlatformError):client_cache.update(text,SETTINGS)
    def test_rejects_injection_bad_keys_and_unbounded_timeouts(self):
        for changed in [dict(url='http://x/\ntrusted-users = *'),dict(publicKey=KEY+'\n'),
                        dict(publicKey='bad:AAAA'),dict(connectTimeoutSeconds=300),
                        dict(stalledTimeoutSeconds=0),dict(url='http://user:pass@localhost/')]:
            with self.assertRaises(PlatformError):client_cache.update('',dict(SETTINGS,**changed))
    def test_no_missing_newline_merges_config_lines(self):
        result=client_cache.update('fallback = false',SETTINGS)
        self.assertIn('fallback = false\n',result)
    def test_refuses_conflicting_station_definitions_outside_block(self):
        with self.assertRaises(PlatformError):
            client_cache.update('extra-trusted-public-keys = station:other\n',SETTINGS)

class ClientCacheInstallTests(unittest.TestCase):
    def test_atomic_install_backup_repeat_and_remove(self):
        import os
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'nix.custom.conf'
            original='extra-substituters = https://old.invalid/\n'
            target.write_text(original);target.chmod(0o644)
            with patch.object(client_cache.os,'geteuid',return_value=0), \
                 patch.object(client_cache,'ROOT_UID',os.getuid()):
                first=client_cache.install(SETTINGS,target=target)
                self.assertEqual(Path(first['backup']).read_text(),original)
                self.assertEqual(Path(first['backup']).stat().st_mode&0o777,0o600)
                self.assertEqual(target.stat().st_mode&0o777,0o644)
                self.assertFalse(client_cache.install(SETTINGS,target=target)['changed'])
                client_cache.install(SETTINGS,uninstall=True,target=target)
                self.assertEqual(target.read_text(),original)
    def test_nonroot_and_symlinks_fail_before_mutation(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'custom'
            with patch.object(client_cache.os,'geteuid',return_value=501):
                with self.assertRaises(PlatformError):client_cache.install(SETTINGS,target=target)
            self.assertFalse(target.exists())
            actual=Path(directory)/'actual';actual.write_text('unchanged')
            target.symlink_to(actual)
            with patch.object(client_cache.os,'geteuid',return_value=0):
                with self.assertRaises(PlatformError):client_cache.install(SETTINGS,target=target)
            self.assertEqual(actual.read_text(),'unchanged')

class ClientCacheVerificationTests(unittest.TestCase):
    def test_automatic_substitution_without_per_command_trust_or_compile(self):
        import hashlib,json,subprocess
        from pathlib import Path
        from unittest.mock import patch
        path='/nix/store/'+'a'*32+'-ospi'
        settings=dict(SETTINGS,verificationPath=path);calls=[];roots=[]
        def execute(args,**kwargs):
            calls.append(args)
            if 'config' in args:
                values={'trusted-public-keys':[KEY],'require-sigs':True,
                        'substituters':['https://cache.nixos.org/',SETTINGS['url']+'?priority=20&retry-attempts=1']}
                return subprocess.CompletedProcess(args,0,json.dumps({k:{'value':v} for k,v in values.items()}),'')
            self.assertNotIn('--from',args)
            self.assertNotIn('trusted-public-keys',args)
            self.assertIn('--realise',args)
            self.assertEqual(args[args.index('max-jobs')+1],'0')
            root=Path(args[args.index('--store')+1].removeprefix('local?root='));roots.append(root)
            out=root/path.lstrip('/');out.mkdir(parents=True)
            lines=[]
            for name in ['tiboot3.bin','tispl.bin','u-boot.img','fitImage.itb']:
                data=name.encode();(out/name).write_bytes(data)
                lines.append(hashlib.sha256(data).hexdigest()+'  '+name+'\n')
            (out/'SHA256SUMS').write_text(''.join(lines))
            return subprocess.CompletedProcess(args,0,'','')
        with patch.object(client_cache.os,'geteuid',return_value=0), \
             patch.object(client_cache.subprocess,'run',side_effect=execute):
            result=client_cache.verify(settings)
        self.assertEqual(len(calls),2);self.assertTrue(result['automaticSubstitution'])
        self.assertFalse(result['compiled']);self.assertTrue(all(not p.exists() for p in roots))
    def test_missing_global_trust_fails_before_fetch(self):
        import json,subprocess
        from unittest.mock import patch
        response=subprocess.CompletedProcess([],0,json.dumps({'trusted-public-keys':{'value':[]},'require-sigs':{'value':True}}),'')
        with patch.object(client_cache.os,'geteuid',return_value=0), \
             patch.object(client_cache.subprocess,'run',return_value=response) as run:
            with self.assertRaises(PlatformError):client_cache.verify(dict(SETTINGS,verificationPath='/nix/store/'+'a'*32+'-ospi'))
        self.assertEqual(run.call_count,1)
