import unittest
from tools.platform.cache_reads import corrupt, store_path
from tools.platform.runtime import PlatformError

class CacheReadTests(unittest.TestCase):
    def test_corrupt_only_named_signature(self):
        original=b'StorePath: /nix/store/example\nSig: station:AAAA\nSig: other:BBBB\n'
        changed=corrupt(original,'station')
        self.assertIn(b'Sig: station:BAAA',changed)
        self.assertIn(b'Sig: other:BBBB',changed)
    def test_no_signature_fails_instead_of_network_only_negative(self):
        with self.assertRaises(PlatformError): corrupt(b'URL: nar/example\n','station')
    def test_reject_bad_store_paths(self):
        for value in ['/tmp/foo','/nix/store/../secret','/nix/store/bad','/nix/store/'+'a'*32+'-x/child']:
            with self.assertRaises(PlatformError): store_path(value)
        self.assertEqual(store_path('/nix/store/'+'a'*32+'-fixture'),'/nix/store/'+'a'*32+'-fixture')

class FullReadCheckTests(unittest.TestCase):
    def test_positive_and_both_negatives_use_isolated_strict_stores(self):
        self.run_check(False)
    def test_network_error_cannot_pass_negative_signature_gate(self):
        with self.assertRaises(PlatformError): self.run_check(True)
    def run_check(self, network_failure):
        import json
        from pathlib import Path
        import subprocess
        import tempfile
        from unittest.mock import patch
        from tools.platform import cache_reads
        artifact='/nix/store/'+'a'*32+'-artifact'
        dep='/nix/store/'+'b'*32+'-dependency'
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*args): return b'StorePath: example\nSig: station:AAAA\n'
        class Opener:
            def open(self,*args,**kwargs): return Response()
        copies=[]
        def execute(args, **kwargs):
            if '--generate-binary-cache-key' in args:
                Path(args[-1]).write_text('unrelated:BBBB\n')
                return subprocess.CompletedProcess(args,0,'','')
            if 'config' in args:
                key=args[args.index('trusted-public-keys')+1]
                values={'trusted-public-keys':[key],'secret-key-files':[],
                        'require-sigs':True,'substituters':[],'max-jobs':0}
                return subprocess.CompletedProcess(args,0,json.dumps({k:{'value':v} for k,v in values.items()}),'')
            self.assertIn('copy',args);self.assertNotIn('--no-check-sigs',args)
            uri=args[args.index('--to')+1];self.assertTrue(uri.startswith('local?root='))
            root=Path(uri.removeprefix('local?root='));copies.append(root)
            if len(copies)==1:
                p=root/artifact.lstrip('/');p.mkdir(parents=True)
                (p/'payload').write_text('signed-cache artifact v1\n')
                (p/'dependency').symlink_to(dep+'/payload')
                d=root/dep.lstrip('/');d.mkdir(parents=True)
                (d/'payload').write_text('signed-cache dependency v1\n')
                return subprocess.CompletedProcess(args,0,'','')
            return subprocess.CompletedProcess(args,1,'','network unavailable' if network_failure else 'invalid signature')
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'fixture').write_text(artifact);(p/'public').write_text('station:AAAA')
            settings={'fixtureFile':str(p/'fixture'),'publicKeyFile':str(p/'public'),
                      'origin':'http://127.0.0.1:8080/cache','nix':'/fixed/nix','nixStore':'/fixed/nix-store'}
            with patch.object(cache_reads.os,'geteuid',return_value=0), \
                 patch.object(cache_reads.urllib.request,'build_opener',return_value=Opener()), \
                 patch.object(cache_reads.subprocess,'run',side_effect=execute):
                result=cache_reads.check(settings)
            self.assertEqual(len(copies),3)
            self.assertEqual(len(set(copies)),3)
            self.assertFalse(result['globalTrustChanged'])
            self.assertTrue(all(not root.exists() for root in copies))
