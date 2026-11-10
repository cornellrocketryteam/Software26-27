"""Receipt receiver with real temporary archives and a modeled Nix store."""
import base64
import hashlib
import importlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

from test_build_cli import BuildFixture, REPO

sys.path.insert(0, str(REPO))
from tools.platform.runtime import PlatformError


class ReceiverTests(BuildFixture):
    def setUp(self):
        super().setUp()
        self.archive = self.base / 'archive'
        self.store = self.base / 'store'
        self.store.mkdir()
        self.output = self.store / ('a' * 32 + '-fit-image')
        self.output.mkdir()
        (self.output / 'fitImage.itb').write_bytes(b'fixture FIT')
        self.manifest = {'schemaVersion': 1, 'releaseId': 'release-1',
                         'artifacts': {'fit': {'storePath': str(self.output)}}}
        self.raw = (json.dumps(self.manifest, indent=4) + '\n').encode()
        self.request = {'protocol': 1, 'releaseId': 'release-1',
                        'manifestSha256': hashlib.sha256(self.raw).hexdigest(),
                        'manifestBase64': base64.b64encode(self.raw).decode(),
                        'storePaths': [str(self.output)]}
        self.original_nix = (self.bin / 'nix').read_text()
        (self.bin / 'nix').write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
base = pathlib.Path(os.environ['FAKE_HOME'])
with (base / 'calls').open('a') as f: f.write(json.dumps(['nix'] + sys.argv[1:]) + '\\n')
assert sys.argv[1:3] == ['store', 'verify'] or sys.argv[1] == 'path-info', sys.argv
if os.environ.get('VERIFY_FAIL') and sys.argv[1:3] == ['store', 'verify']: sys.exit(1)
if os.environ.get('INFO_FAIL') and sys.argv[1] == 'path-info': sys.exit(1)
''')

    def receive(self, request=None, **env):
        module = importlib.import_module('tools.platform.receiver')
        with patch.dict('os.environ', {**self.env, **env}):
            return module.receive(self.archive, 'station-archive-1',
                                  json.dumps(request or self.request).encode(), store_dir=str(self.store))

    def receipt_path(self):
        return self.archive / 'releases/release-1/receipt.json'

    def test_receiver_is_available(self):
        self.assertIsNotNone(importlib.util.find_spec('tools.platform.receiver'),
                             'durable receipt receiver has not been implemented')

    def test_acknowledges_only_after_archiving_exact_bytes_verification_and_roots(self):
        receipt = self.receive()
        self.assertEqual((self.archive / 'releases/release-1/manifest.json').read_bytes(), self.raw)
        self.assertEqual(receipt['archiveId'], 'station-archive-1')
        self.assertEqual(receipt['manifestSha256'], self.request['manifestSha256'])
        self.assertEqual(receipt['storePaths'], [str(self.output)])
        self.assertIs(receipt['retained'], True)
        self.assertEqual(json.loads(self.receipt_path().read_text()), receipt)
        self.assertEqual(Path(receipt['roots'][str(self.output)]).readlink(), self.output)
        self.assertTrue(any('--recursive' in c and '--no-trust' in c for c in self.calls('nix')))
        self.assertTrue(self.calls('nix-store'))

    def test_retry_returns_same_receipt_and_repairs_missing_root(self):
        first = self.receive()
        Path(first['roots'][str(self.output)]).unlink()
        self.assertEqual(self.receive(), first)
        self.assertTrue(Path(first['roots'][str(self.output)]).exists())

    def test_verification_failure_never_writes_receipt(self):
        with self.assertRaises(PlatformError): self.receive(VERIFY_FAIL='1')
        self.assertFalse(self.receipt_path().exists())
        self.assertTrue(any(c[1:3] == ['store', 'verify'] for c in self.calls('nix')))
        self.assertIs(self.receive()['retained'], True)

    def test_output_not_registered_in_store_never_reaches_realization(self):
        with self.assertRaises(PlatformError): self.receive(INFO_FAIL='1')
        self.assertEqual(self.calls('nix-store'), [])
        self.assertFalse(self.archive.exists())

    def test_root_registration_failure_never_writes_receipt(self):
        with self.assertRaises(PlatformError): self.receive(ROOT_FAIL='1')
        self.assertFalse(self.receipt_path().exists())

    def test_digest_path_and_release_identity_rejections_make_no_archive(self):
        cases = [dict(self.request, manifestSha256='0' * 64),
                 dict(self.request, releaseId='../escape'),
                 dict(self.request, protocol=True),
                 dict(self.request, storePaths=['/etc/passwd']),
                 dict(self.request, manifestBase64='not-base64')]
        for request in cases:
            with self.subTest(request=request):
                with self.assertRaises(PlatformError): self.receive(request)
                self.assertFalse(self.archive.exists())

    def test_same_release_id_with_other_manifest_is_rejected(self):
        original = self.receive()
        raw = self.raw + b' '
        request = dict(self.request, manifestBase64=base64.b64encode(raw).decode(),
                       manifestSha256=hashlib.sha256(raw).hexdigest())
        with self.assertRaises(PlatformError): self.receive(request)
        self.assertEqual(json.loads(self.receipt_path().read_text()), original)

    def test_changed_archive_identity_rejected(self):
        self.receive()
        module = importlib.import_module('tools.platform.receiver')
        with self.assertRaises(PlatformError):
            module.receive(self.archive, 'another-archive', json.dumps(self.request).encode(),
                           store_dir=str(self.store))

    def test_crash_before_receipt_persistence_retries_without_false_ack(self):
        module = importlib.import_module('tools.platform.receiver')
        original = module.atomic_json
        def interrupt(path, value):
            if Path(path).name == 'receipt.json': raise OSError('simulated interrupted persistence')
            return original(path, value)
        with patch.object(module, 'atomic_json', side_effect=interrupt):
            with self.assertRaises(OSError): self.receive()
        self.assertFalse(self.receipt_path().exists())
        self.assertIs(self.receive()['retained'], True)

    def test_oversized_request_fails_before_state_changes(self):
        module = importlib.import_module('tools.platform.receiver')
        with self.assertRaises(PlatformError):
            module.receive(self.archive, 'station-archive-1', b' ' * (2 * 1024 * 1024 + 1))
        self.assertFalse(self.archive.exists())

    def test_cached_receipt_must_describe_this_actual_archive_location(self):
        receipt = self.receive()
        receipt['archivePath'] = '/other/archive'
        receipt['roots'] = {str(self.output): '/other/archive/roots/release-1/0'}
        self.receipt_path().write_text(json.dumps(receipt))
        with self.assertRaises(PlatformError): self.receive()

    def test_derivation_and_absent_output_never_trigger_realization(self):
        for name in ('b' * 32 + '-build.drv', 'c' * 32 + '-missing-output'):
            with self.subTest(name=name):
                manifest = dict(self.manifest, artifacts={'fit': {'storePath': str(self.store / name)}})
                raw = json.dumps(manifest).encode()
                request = dict(self.request, storePaths=[str(self.store / name)],
                               manifestBase64=base64.b64encode(raw).decode(),
                               manifestSha256=hashlib.sha256(raw).hexdigest())
                with self.assertRaises(PlatformError): self.receive(request)
                self.assertEqual(self.calls('nix-store'), [])

    def test_retry_reestablishes_durability_after_rename_before_directory_fsync(self):
        from tools.platform import runtime, receiver
        original = runtime.sync_dir
        def fail_after_receipt_rename(path):
            if Path(path) == self.receipt_path().parent and self.receipt_path().exists():
                raise OSError('simulated directory fsync interruption after rename')
            return original(path)
        with patch.object(runtime, 'sync_dir', side_effect=fail_after_receipt_rename):
            with self.assertRaises(OSError): self.receive()
        self.assertTrue(self.receipt_path().exists())
        with patch.object(receiver, 'sync_dir', side_effect=fail_after_receipt_rename):
            with self.assertRaises(OSError): self.receive()
        self.assertIs(self.receive()['retained'], True)

    def test_registered_archive_root_survives_modeled_gc(self):
        receipt = self.receive()
        unretained = self.store / ('b' * 32 + '-unretained')
        unretained.mkdir()
        import subprocess
        result = subprocess.run([str(self.bin / 'nix-store'), '--gc'], env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assert_ok(result)
        self.assertTrue(self.output.exists())
        self.assertFalse(unretained.exists())
        self.assertEqual(self.receive(), receipt)
