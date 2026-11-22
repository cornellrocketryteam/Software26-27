"""Subprocess integration tests; fake programs model stores, roots and transport."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]

FAKE = r'''#!/usr/bin/env python3
import hashlib, json, os, pathlib, re, shutil, sys, time
p = pathlib.Path
args = sys.argv[1:]
name = p(sys.argv[0]).name
base = p(os.environ['FAKE_HOME'])
with (base / 'calls').open('a') as f:
    f.write(json.dumps([name] + args) + '\n')

def physical(store, remote=False):
    if store.startswith('/nix/store/'):
        return base / ('worker-store' if remote else 'store') / p(store).name
    return p(store)

def make_output(target, attr):
    target.mkdir(parents=True, exist_ok=True)
    files = {'fitImage': ['fitImage.itb'], 'ospiImage': ['fitImage.itb','tiboot3.bin','tispl.bin','u-boot.img','partitions','SHA256SUMS'],
             'sdImage': ['fill-station.img'], 'dataCardImage': ['fill-station-data-card.img'], 'toplevel': ['activate']}
    for file in files[attr]: (target / file).write_bytes((file + '\n').encode())

def registered(root, store):
    registry = base / 'gcroots' / hashlib.sha256(str(root).encode()).hexdigest()
    return (root.is_symlink() and str(root.readlink()) == store
            and registry.is_symlink() and registry.readlink() == root)

if name == 'ssh':
    if os.environ.get('SSH_FAIL'):
        sys.stderr.write('transport unavailable\n'); sys.exit(255)
    if os.environ.get('SSH_SLEEP'):
        time.sleep(5)
    if args and args[-1] == 'crt-platform-builder-retain-v1':
        raw = sys.stdin.buffer.read(4097)
        assert len(raw) <= 4096
        request = json.loads(raw)
        assert set(request) == {'protocol', 'action', 'workerId', 'token', 'drvPath'}
        assert type(request['protocol']) is int and request['protocol'] == 1
        assert request['workerId'] == 'fixture-worker'
        assert re.fullmatch('[0-9a-f]{32}', request['token'])
        assert re.fullmatch('/nix/store/[a-z0-9]{32}-[A-Za-z0-9._-]+[.]drv', request['drvPath'])
        assert request['action'] in ('realise', 'release')
        with (base / 'retention-requests').open('a') as stream:
            stream.write(json.dumps(request) + '\n')
        store = request['drvPath'][:-4]
        retained = base / 'worker-retention'; retained.mkdir(exist_ok=True)
        record = retained / (request['token'] + '.json')
        root = retained / request['token']
        if record.exists():
            previous = json.loads(record.read_text())
            assert all(previous[key] == request[key] for key in ('token', 'drvPath', 'workerId'))
        if request['action'] == 'realise':
            # The client's durable token must precede the first wire request.
            journal = p(os.environ['CRT_PLATFORM_STATE_DIR']) / 'transfers' / (request['token'] + '.json')
            assert json.loads(journal.read_text())['drvPath'] == request['drvPath']
            if os.environ.get('BUILD_FAIL'):
                sys.stderr.write('compiler error: intentional fixture failure\n'); sys.exit(100)
            target = physical(store, remote=True)
            make_output(target, p(store).name[33:])
            if not root.is_symlink(): root.symlink_to(target)
            record.write_text(json.dumps(request))
            reply = {**request, 'retained': True, 'storePath': store}
            if os.environ.get('RETENTION_REPLY_OVERRIDE'):
                reply.update(json.loads(os.environ['RETENTION_REPLY_OVERRIDE']))
            print(json.dumps(reply)); sys.exit(0)
        # This assertion models the client handoff, not server access to a
        # remote filesystem. It fails if release precedes actual local success.
        journal = p(os.environ['CRT_PLATFORM_STATE_DIR']) / 'transfers' / (request['token'] + '.json')
        local = json.loads(journal.read_text())
        local_root = p(local['gcRoot'])
        assert local['storePath'] == store and physical(store).is_dir()
        assert registered(local_root, store)
        calls = [json.loads(line) for line in (base / 'calls').read_text().splitlines()]
        assert ['nix-store', '--check-validity', store] in calls
        assert ['nix-store', '--query', '--roots', store] in calls
        root.unlink(missing_ok=True); record.unlink(missing_ok=True)
        if os.environ.get('RELEASE_LOST_ACK'):
            sys.stderr.write('release reply disconnected\n'); sys.exit(255)
        print(json.dumps({**request, 'released': True})); sys.exit(0)
    if args and args[-1] == 'crt-platform-cache-receive-v1':
        request = json.load(sys.stdin)
        scenario = os.environ.get('RECEIPT_SCENARIO', 'valid')
        root = '/var/lib/ground-cache-archive'
        receipt = {k: request[k] for k in ('protocol', 'releaseId', 'manifestSha256', 'storePaths')}
        receipt.update(archiveId='station-archive-1', archivePath=root, retained=True,
                       roots={s: root + '/roots/' + request['releaseId'] + '/' + str(i)
                              for i, s in enumerate(request['storePaths'])})
        if scenario == 'invalid-json': print('not JSON'); sys.exit(0)
        if scenario == 'wrong-digest': receipt['manifestSha256'] = '0' * 64
        if scenario == 'wrong-archive': receipt['archiveId'] = 'different-archive'
        if scenario == 'wrong-paths': receipt['storePaths'] = ['/nix/store/wrong']
        if scenario == 'missing-root': receipt['roots'] = {}
        if scenario == 'not-retained': receipt['retained'] = False
        print(json.dumps(receipt)); sys.exit(0)
    scenario = os.environ.get('STATION_HEALTH')
    health = {'protocol': 1, 'workerId': 'fixture-worker', 'platforms': ['aarch64-linux', 'x86_64-linux'],
                      'available': scenario != 'busy', 'operationalMode': 'field' if scenario == 'field' else 'maintenance',
                      'freeBytes': 0 if scenario == 'full' else 200_000_000_000}
    if os.environ.get('HEALTH_OVERRIDE'): health.update(json.loads(os.environ['HEALTH_OVERRIDE']))
    print(json.dumps(health))
elif name == 'nix-store':
    if '--check-validity' in args:
        if os.environ.get('VALIDITY_FAIL') or not physical(args[-1]).exists(): sys.exit(1)
        sys.exit(0)
    if '--roots' in args:
        if not os.environ.get('UNREGISTERED_ROOT'):
            for link in (base / 'gcroots').iterdir():
                root = link.readlink()
                if registered(root, args[-1]): print(str(root) + ' -> ' + args[-1])
        sys.exit(0)
    if args == ['--gc']:
        import shutil
        registered = base / 'gcroots'
        retained = {r.resolve() for r in registered.iterdir() if r.exists()}
        for item in (base / 'store').iterdir():
            if item.resolve() not in retained: shutil.rmtree(item)
        sys.exit(0)
    if os.environ.get('ROOT_FAIL'):
        sys.exit(1)
    assert '--indirect' in args and '--realise' in args
    root = p(args[args.index('--add-root') + 1]); target = args[args.index('--realise') + 1]
    if target.startswith('/nix/store/'):
        assert args[args.index('substituters') + 1] == 'ssh-ng://builder@station.invalid'
        assert args[args.index('require-sigs') + 1] == 'true'
        with (base / 'import-ssh-options').open('a') as stream:
            stream.write(json.dumps(os.environ['NIX_SSHOPTS']) + '\n')
        if os.environ.get('COPY_SLEEP'): time.sleep(5)
        if os.environ.get('COPY_FAIL'):
            sys.stderr.write('copy interrupted\n'); sys.exit(1)
        if not physical(target).exists():
            shutil.copytree(physical(target, remote=True), physical(target))
    root.parent.mkdir(parents=True, exist_ok=True)
    if not root.is_symlink(): root.symlink_to(target + '-wrong' if os.environ.get('WRONG_ROOT') else target)
    registry = base / 'gcroots'; registry.mkdir(exist_ok=True)
    import hashlib
    link = registry / hashlib.sha256(str(root).encode()).hexdigest()
    if not link.is_symlink(): link.symlink_to(root)
    print(root)
elif args[:2] == ['store', 'ping']:
    if os.environ.get('LOCAL_DOWN') and '--store' not in args: sys.exit(1)
    print('{}')
elif args[:2] == ['config', 'show']:
    platforms = [] if os.environ.get('LOCAL_INCOMPATIBLE') else ['aarch64-linux']
    print(json.dumps({k: {'value': v} for k,v in {
        'system': 'aarch64-darwin', 'extra-platforms': [], 'builders': '', 'max-jobs': 8,
        'external-builders': [{'program': '/fake/determinate-nixd', 'args': ['builder'], 'systems': platforms}]
    }.items()}))
elif args and args[0] == 'copy':
    archive = base / 'remote'; archive.mkdir(exist_ok=True)
    if os.environ.get('COPY_SLEEP'): time.sleep(5)
    if os.environ.get('COPY_FAIL'):
        (archive / '.partial').touch()
        sys.stderr.write('copy interrupted\n'); sys.exit(1)
    (archive / '.partial').unlink(missing_ok=True)
    for a in args:
        if a.startswith(str(base / 'store')): (archive / p(a).name).touch()
elif args and args[0] == 'eval':
    assert '--raw' in args and '--eval-store' in args
    assert args[args.index('--eval-store') + 1] == args[args.index('--store') + 1]
    installable = args[-1]
    assert installable.endswith('.drvPath')
    attr = installable.split('.')[-2]
    print('/nix/store/' + 'a' * 32 + '-' + attr + '.drv')
elif args and args[0] == 'build':
    if '--dry-run' in args:
        if os.environ.get('EVALUATION_SLEEP'):
            time.sleep(float(os.environ['EVALUATION_SLEEP']))
        if os.environ.get('PREFLIGHT_FAIL'):
            sys.stderr.write('missing locked source /fake/missing-input\n'); sys.exit(1)
        print('[]'); sys.exit(0)
    if os.environ.get('BUILD_FAIL'):
        sys.stderr.write('compiler error: intentional fixture failure\n'); sys.exit(100)
    attrs = [a for a in args if '#mixos' in a or '#nixos' in a]
    if not attrs: sys.exit(9)
    attr = attrs[0].split('.')[-1]
    target = base / 'store' / ('aaaaaaaa-' + attr)
    make_output(target, attr)
    if '--out-link' in args:
        link = p(args[args.index('--out-link') + 1]); link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
    print(json.dumps([{'drvPath': str(target) + '.drv', 'outputs': {'out': str(target)}}]))
else:
    sys.stderr.write('unexpected fake invocation: ' + repr(args)); sys.exit(10)
'''


class BuildFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        # A separate Git working copy keeps every build/snapshot/output inside the fixture.
        for file in ('flake.nix', 'flake.lock', 'fill-station/hardware/profiles/liquid.json',
                     'fill-station/hardware/profiles/hybrid.json'):
            dest = self.repo / file
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text('{}\n')
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
        self.bin = self.base / 'bin'; self.bin.mkdir()
        for name in ('nix', 'nix-store', 'ssh'):
            f = self.bin / name; f.write_text(FAKE); f.chmod(0o755)
        self.state = self.base / 'state'
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        FAKE_HOME=str(self.base), CRT_PLATFORM_STATE_DIR=str(self.state), PYTHONDONTWRITEBYTECODE='1')
        self.config = self.base / 'config.json'
        self.config.write_text('{}')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.DEVNULL)

    def run_cli(self, *args, **env):
        # Test the importable entrypoint against an isolated source repository.
        # The protocol carries canonical /nix/store names. Map only inventory
        # reads into the fixture's physical store; never write the host store or
        # bypass production token, path, root, validity or response checks.
        code = '''
import os, sys
from pathlib import Path
from tools.platform import build
from tools.platform.manifest import artifact_files
from tools.platform.cli import main
def fixture_files(store):
    physical = Path(os.environ['FAKE_HOME']) / 'store' / Path(store).name if store.startswith('/nix/store/') else store
    return artifact_files(physical)
build.artifact_files = fixture_files
raise SystemExit(main(sys.argv[2:], repo=sys.argv[1]))
'''
        return subprocess.run([sys.executable, '-c', code, str(self.repo), '--config', str(self.config), *args],
                              cwd=REPO, env={**self.env, **env}, text=True, capture_output=True, timeout=20)

    def build(self, *args, **env):
        return self.run_cli('build', 'fill-station', '--vehicle', 'liquid', *args, **env)

    def calls(self, command=None):
        records = [json.loads(s) for s in (self.base / 'calls').read_text().splitlines()] if (self.base / 'calls').exists() else []
        return [r for r in records if command is None or r[0] == command]

    def retention_requests(self):
        path = self.base / 'retention-requests'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def manifests(self):
        return [json.loads(f.read_text()) for f in sorted((self.repo / 'outputs/platform').glob('*/manifest.json'))]

    def station_config(self, prefer=True, worker_id=None):
        known = self.base / 'known_hosts'; known.write_text('fixture pinned host key\n')
        conf = {'policy': {'preferStation': prefer, 'probeTimeoutSeconds': 2},
                'station': {'store': 'ssh-ng://builder@station.invalid', 'sshTarget': 'builder@station.invalid',
                            'knownHosts': str(known), 'validated': True, 'platforms': ['aarch64-linux'],
                            'minFreeBytes': 100_000_000_000}}
        if worker_id is not None:
            conf['station']['workerId'] = worker_id
        self.config.write_text(json.dumps(conf))
        return conf

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class BuildCLI(BuildFixture):
    def test_default_build_only_produces_ospi(self):
        self.assert_ok(self.build('--builder', 'local'))
        self.assertEqual(set(self.manifests()[0]['artifacts']), {'ospi'})
        builds = [r for r in self.calls('nix') if 'build' in r and '--dry-run' not in r]
        self.assertEqual(len(builds), 1)
        self.assertTrue(any('#mixosConfigurations.fill-station-liquid.config.system.build.ospiImage' in a for a in builds[0]))

    def test_release_uses_raw_arm_graph_and_real_roots_and_hashes(self):
        self.assert_ok(self.build('--artifact', 'release', '--builder', 'local'))
        manifests = self.manifests(); self.assertEqual(len(manifests), 1)
        m = manifests[0]
        self.assertEqual(m['build']['platform'], 'aarch64-linux')
        self.assertEqual(m['vehicle'], 'liquid')
        self.assertEqual(set(m['artifacts']), {'sd', 'ospi', 'data'})
        for artifact in m['artifacts'].values():
            self.assertTrue(Path(artifact['gcRoot']).is_symlink())
            for f in artifact['files']:
                self.assertEqual(f['sha256'], hashlib.sha256(Path(f['path']).read_bytes()).hexdigest())
        roots = self.calls('nix-store'); self.assertEqual(len(roots), 3)
        self.assertTrue(all('--indirect' in r for r in roots))
        builds = [r for r in self.calls('nix') if 'build' in r and '--dry-run' not in r]
        self.assertEqual(len(builds), 3)
        self.assertTrue(any('#mixosConfigurations.fill-station-liquid.config.system.build.ospiImage' in a for r in builds for a in r))
        self.assertEqual(m['publication']['state'], 'pending')
        self.assertFalse(m['source']['dirty'])
        self.assertTrue(Path(m['source']['snapshot']).is_dir())
        self.assertEqual(m['deployment']['state'], 'not-deployed')

    def test_missing_vehicle_and_incomplete_deploy_are_errors(self):
        self.assertNotEqual(self.run_cli('build', 'fill-station').returncode, 0)
        self.assertNotEqual(self.run_cli('deploy').returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_dry_run_has_no_subprocess_or_filesystem_effects(self):
        self.assert_ok(self.build('--artifact', 'release', '--dry-run'))
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.state.exists())
        self.assertFalse((self.repo / 'outputs').exists())

    def test_default_auto_keeps_determinate_external_builder(self):
        self.assert_ok(self.build('--artifact', 'fit'))
        self.assertEqual(self.manifests()[0]['build']['worker'], 'local')
        self.assertEqual(self.calls('ssh'), [])
        self.assertTrue(all('external-builders' not in r for r in self.calls('nix')))

    def test_station_is_disabled_without_validation(self):
        conf = self.station_config(); conf['station']['validated'] = False
        self.config.write_text(json.dumps(conf))
        result = self.build('--builder', 'station')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('validated', result.stderr)
        self.assertEqual(self.calls('ssh'), [])

    def test_preferred_station_unreachable_falls_back_before_build(self):
        self.station_config()
        self.assert_ok(self.build('--artifact', 'fit', SSH_FAIL='1'))
        self.assertEqual(self.manifests()[0]['build']['worker'], 'local')
        self.assertTrue(self.calls('ssh'))

    def test_station_health_is_bounded(self):
        self.station_config()
        self.assert_ok(self.build('--artifact', 'fit', SSH_SLEEP='1'))
        self.assertEqual(self.manifests()[0]['build']['worker'], 'local')

    def test_compiler_error_is_not_retried(self):
        self.station_config(worker_id='fixture-worker')
        result = self.build('--artifact', 'fit', BUILD_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('compiler error', result.stderr)
        builds = [r for r in self.calls('nix') if 'build' in r and '--dry-run' not in r]
        self.assertEqual(builds, [])
        self.assertEqual([r['action'] for r in self.retention_requests()], ['realise'])
        self.assertEqual(self.manifests(), [])

    def test_incompatible_local_routes_to_validated_station_before_build(self):
        self.station_config(prefer=False, worker_id='fixture-worker')
        self.assert_ok(self.build('--artifact', 'fit', LOCAL_INCOMPATIBLE='1'))
        self.assertEqual(self.manifests()[0]['build']['worker'], 'station')
        imports = [r for r in self.calls('nix-store') if '--realise' in r]
        self.assertEqual(len(imports), 1)
        self.assertIn('substituters', imports[0])
        self.assertIn('ssh-ng://builder@station.invalid', imports[0])
        self.assertEqual([r['action'] for r in self.retention_requests()], ['realise', 'release'])

    def test_offline_excludes_station_and_reports_missing_inputs_before_build(self):
        self.station_config()
        result = self.build('--offline', PREFLIGHT_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('/fake/missing-input', result.stderr)
        self.assertEqual(self.calls('ssh'), [])
        self.assertFalse(any('build' in r and '--dry-run' not in r for r in self.calls('nix')))

    def test_offline_success_uses_no_network_cache_or_ssh_workers(self):
        self.station_config()
        self.assert_ok(self.build('--offline', '--artifact', 'fit'))
        self.assertEqual(self.calls('ssh'), [])
        builds = [r for r in self.calls('nix') if 'build' in r]
        self.assertTrue(all('--offline' in r and 'substituters' in r and '--builders' in r for r in builds))

    def test_dirty_snapshot_records_working_source_and_excludes_untracked(self):
        (self.repo / 'flake.nix').write_text('{ modified = true; }')
        (self.repo / 'untracked.txt').write_text('not a git flake input')
        self.assert_ok(self.build('--artifact', 'fit'))
        source = self.manifests()[0]['source']
        self.assertTrue(source['dirty'])
        self.assertEqual((Path(source['snapshot']) / 'flake.nix').read_text(), '{ modified = true; }')
        self.assertFalse((Path(source['snapshot']) / 'untracked.txt').exists())
        self.assertIn('untracked.txt', source['excludedUntracked'])

    def test_x86_is_explicit_and_station_capability_is_required(self):
        self.assert_ok(self.build('--artifact', 'fit', '--build-platform', 'x86_64-linux', '--dry-run'))
        conf = self.station_config(worker_id='fixture-worker')
        result = self.build('--artifact', 'fit', '--build-platform', 'x86_64-linux', '--builder', 'station')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls('ssh'), [])
        self.assertIn('x86_64-linux', result.stderr)
        conf['station']['platforms'].append('x86_64-linux'); self.config.write_text(json.dumps(conf))
        self.assert_ok(self.build('--artifact', 'fit', '--build-platform', 'x86_64-linux', '--builder', 'station'))
        self.assertEqual(self.manifests()[0]['build']['platform'], 'x86_64-linux')
        self.assertTrue(any('#mixosBuildConfigurations."x86_64-linux".fill-station-liquid.config.system.build.fitImage' in a for r in self.calls('nix') for a in r))

    def test_ground_station_services_profile_selects_installed_target(self):
        result = self.run_cli('build', 'ground-station', '--profile', 'um560-services', '--dry-run')
        self.assert_ok(result)
        self.assertEqual(json.loads(result.stdout)['attributes']['system'],
                         'nixosConfigurations.ground-station-um560-services.config.system.build.toplevel')
        self.assertEqual(self.calls(), [])

    def test_ground_station_uses_only_existing_expected_toplevel(self):
        self.assert_ok(self.run_cli('build', 'ground-station', '--builder', 'station', '--dry-run'))
        self.assertEqual(self.calls(), [])

    def test_root_registration_failure_does_not_publish_success(self):
        result = self.build('--artifact', 'fit', ROOT_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.manifests(), [])
        self.assertFalse(list((self.state / 'outbox').glob('*.json')))

    def test_status_is_read_only_and_check_does_not_build(self):
        self.assert_ok(self.run_cli('status'))
        self.assertFalse(self.state.exists())
        self.assert_ok(self.run_cli('check'))
        self.assertFalse(any('build' in r or '--realise' in r for r in self.calls()))


class BuildFailureCases(BuildFixture):
    def test_cold_evaluation_has_independent_timeout(self):
        for evaluation in (None, 300):
            with self.subTest(evaluation=evaluation):
                policy = {'probeTimeoutSeconds': 1, 'buildTimeoutSeconds': 30}
                if evaluation is not None:
                    policy['evaluationTimeoutSeconds'] = evaluation
                self.config.write_text(json.dumps({'policy': policy}))
                self.assert_ok(self.build('--artifact', 'fit', '--builder', 'local', EVALUATION_SLEEP='1.5'))

    def test_evaluation_timeout_is_validated_and_enforced(self):
        for value in (0, -1, True, '300', 3601):
            with self.subTest(value=value):
                self.config.write_text(json.dumps({'policy': {'evaluationTimeoutSeconds': value}}))
                result = self.build('--dry-run')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('evaluationTimeoutSeconds', result.stderr)
        self.config.write_text(json.dumps({'policy': {'evaluationTimeoutSeconds': 3600}}))
        self.assert_ok(self.build('--dry-run'))
        self.config.write_text(json.dumps({'policy': {'evaluationTimeoutSeconds': 1, 'buildTimeoutSeconds': 30}}))
        result = self.build('--artifact', 'fit', EVALUATION_SLEEP='1.5')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('timed out', result.stderr)
        self.assertFalse(any('build' in r and '--dry-run' not in r for r in self.calls('nix')))

    def test_assume_unchanged_modified_bytes_are_development(self):
        self.git('update-index', '--assume-unchanged', 'flake.nix')
        (self.repo / 'flake.nix').write_text('{ hidden = true; }\n')
        self.assertEqual(self.git('diff', 'HEAD', '--name-only'), b'')
        self.assert_ok(self.build('--artifact', 'fit'))
        manifest = self.manifests()[0]
        self.assertTrue(manifest['source']['dirty'])
        self.assertEqual(manifest['classification'], 'development')

    def build_with_copy_hook(self, hook):
        import contextlib
        import io
        from unittest.mock import patch
        from tools.platform.cli import main
        import shutil
        copy = shutil.copy2
        def copying(source, destination, *args, **kwargs):
            return hook(copy, Path(source), Path(destination), *args, **kwargs)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.env), patch('tools.platform.manifest.shutil.copy2', side_effect=copying), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(['--config', str(self.config), 'build', 'fill-station', '--vehicle', 'liquid',
                           '--artifact', 'fit'], repo=self.repo)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_edit_during_copy_classifies_captured_bytes_as_development(self):
        def mutate(copy, source, destination, *args, **kwargs):
            if source.name == 'flake.nix':
                source.write_text('{ duringCopy = true; }\n')
            return copy(source, destination, *args, **kwargs)
        code, out, err = self.build_with_copy_hook(mutate)
        self.assertEqual(code, 0, out + err)
        manifest = self.manifests()[0]
        self.assertTrue(manifest['source']['dirty'])
        self.assertEqual(manifest['classification'], 'development')
        self.assertEqual((Path(manifest['source']['snapshot']) / 'flake.nix').read_text(), '{ duringCopy = true; }\n')

    def test_edit_after_copy_does_not_change_captured_source_classification(self):
        def mutate(copy, source, destination, *args, **kwargs):
            result = copy(source, destination, *args, **kwargs)
            if source.name == 'flake.nix':
                source.write_text('{ afterCopy = true; }\n')
            return result
        code, out, err = self.build_with_copy_hook(mutate)
        self.assertEqual(code, 0, out + err)
        manifest = self.manifests()[0]
        self.assertFalse(manifest['source']['dirty'])
        self.assertEqual(manifest['classification'], 'candidate')
        self.assertEqual((Path(manifest['source']['snapshot']) / 'flake.nix').read_bytes(), self.git('show', 'HEAD:flake.nix'))

    def test_executable_mode_hidden_by_git_configuration_is_development(self):
        self.git('config', 'core.filemode', 'false')
        (self.repo / 'flake.nix').chmod(0o755)
        self.assertEqual(self.git('diff', 'HEAD', '--name-only'), b'')
        self.assert_ok(self.build('--artifact', 'fit'))
        self.assertEqual(self.manifests()[0]['classification'], 'development')

    def test_changed_tracked_type_is_development(self):
        self.git('update-index', '--assume-unchanged', 'flake.nix')
        (self.repo / 'flake.nix').unlink()
        (self.repo / 'flake.nix').symlink_to('flake.lock')
        self.assertEqual(self.git('diff', 'HEAD', '--name-only'), b'')
        self.assert_ok(self.build('--artifact', 'fit'))
        self.assertEqual(self.manifests()[0]['classification'], 'development')

    def test_head_moving_during_copy_aborts_before_compilation(self):
        old = self.git('rev-parse', 'HEAD').decode().strip()
        new = self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                       'commit-tree', f'{old}^{{tree}}', '-p', old, '-m', 'same tree, new commit').decode().strip()
        def move_head(copy, source, destination, *args, **kwargs):
            if source.name == 'flake.nix':
                self.git('update-ref', 'HEAD', new, old)
            return copy(source, destination, *args, **kwargs)
        code, out, err = self.build_with_copy_hook(move_head)
        self.assertNotEqual(code, 0, out + err)
        self.assertIn('HEAD changed', err)
        self.assertEqual(self.manifests(), [])
        self.assertFalse(any('build' in r for r in self.calls('nix')))

    def test_auto_station_preference_selects_x86_graph_without_explicit_platform(self):
        conf = self.station_config(worker_id='fixture-worker')
        conf['station']['platforms'] = ['x86_64-linux']
        self.config.write_text(json.dumps(conf))
        self.assert_ok(self.build('--artifact', 'fit'))
        manifest = self.manifests()[0]
        self.assertEqual(manifest['build']['worker'], 'station')
        self.assertEqual(manifest['build']['platform'], 'x86_64-linux')
        self.assertIn('mixosBuildConfigurations."x86_64-linux"', manifest['artifacts']['fit']['attribute'])

    def test_local_unavailable_falls_back_to_station_x86_graph_before_build(self):
        conf = self.station_config(prefer=False, worker_id='fixture-worker')
        conf['station']['platforms'] = ['x86_64-linux']
        self.config.write_text(json.dumps(conf))
        self.assert_ok(self.build('--artifact', 'fit', LOCAL_DOWN='1'))
        self.assertEqual(self.manifests()[0]['build']['platform'], 'x86_64-linux')
        self.assertEqual(self.manifests()[0]['build']['worker'], 'station')

    def test_explicit_station_chooses_advertised_x86_graph(self):
        conf = self.station_config(worker_id='fixture-worker')
        conf['station']['platforms'] = ['x86_64-linux']
        self.config.write_text(json.dumps(conf))
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'station'))
        self.assertEqual(self.manifests()[0]['build']['platform'], 'x86_64-linux')

    def test_explicit_platform_remains_constraint_when_station_preferred(self):
        conf = self.station_config(worker_id='fixture-worker')
        conf['station']['platforms'] = ['x86_64-linux']
        self.config.write_text(json.dumps(conf))
        self.assert_ok(self.build('--artifact', 'fit', '--build-platform', 'aarch64-linux'))
        self.assertEqual(self.manifests()[0]['build']['platform'], 'aarch64-linux')
        self.assertEqual(self.manifests()[0]['build']['worker'], 'local')

    def test_unavailable_x86_station_falls_back_to_arm_local_before_build(self):
        conf = self.station_config(worker_id='fixture-worker')
        conf['station']['platforms'] = ['x86_64-linux']
        self.config.write_text(json.dumps(conf))
        self.assert_ok(self.build('--artifact','fit',STATION_HEALTH='busy'))
        manifest=self.manifests()[0]
        self.assertEqual((manifest['build']['worker'],manifest['build']['platform']),('local','aarch64-linux'))
        self.assertIsNone(manifest['build']['workerId'])
        self.assertEqual(len([r for r in self.calls('nix') if 'build' in r and '--dry-run' not in r]),1)

    def test_x86_station_compilation_failure_does_not_start_local_compilation(self):
        conf = self.station_config(worker_id='fixture-worker')
        conf['station']['platforms'] = ['x86_64-linux']
        self.config.write_text(json.dumps(conf))
        result=self.build('--artifact','fit',BUILD_FAIL='1')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(len(self.retention_requests()),1)
        self.assertFalse(any(r[:3]==['nix','store','ping'] for r in self.calls('nix')))
        self.assertFalse(any('build' in r and '--dry-run' not in r for r in self.calls('nix')))

    def test_dry_run_shows_worker_graph_candidates_without_probes(self):
        conf = self.station_config(worker_id='fixture-worker')
        conf['station']['platforms'] = ['x86_64-linux']
        self.config.write_text(json.dumps(conf))
        result=self.build('--artifact','fit','--dry-run');self.assert_ok(result)
        candidates=json.loads(result.stdout)['routingCandidates']
        self.assertEqual((candidates[0]['worker'],candidates[0]['platform']),('station','x86_64-linux'))
        self.assertIn('mixosBuildConfigurations."x86_64-linux"',candidates[0]['attributes']['fit'])
        self.assertEqual(self.calls(),[])

    def test_hybrid_maps_to_original_machine(self):
        self.assert_ok(self.run_cli('build', 'fill-station', '--vehicle', 'hybrid', '--artifact', 'fit'))
        self.assertIn('mixosConfigurations.fill-station.config.system.build.fitImage',
                      self.manifests()[0]['artifacts']['fit']['attribute'])

    def test_ground_station_build_records_x86_and_null_vehicle(self):
        conf = self.station_config(worker_id='fixture-worker')
        conf['station']['platforms'] = ['x86_64-linux']; self.config.write_text(json.dumps(conf))
        self.assert_ok(self.run_cli('build', 'ground-station', '--profile', 'um560-services', '--builder', 'station'))
        m = self.manifests()[0]
        self.assertEqual(m['artifacts']['system']['attribute'],
                         'nixosConfigurations.ground-station-um560-services.config.system.build.toplevel')
        self.assertEqual(m['build']['platform'], 'x86_64-linux')
        self.assertIsNone(m['vehicle'])
        self.assertEqual(set(m['artifacts']), {'system'})

    def test_remote_store_build_does_not_register_local_outlink_in_remote_store(self):
        self.station_config(worker_id='fixture-worker')
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'station'))
        builds = [r for r in self.calls('nix') if 'build' in r and '--dry-run' not in r]
        self.assertEqual(builds, [])
        evaluations = [r for r in self.calls('nix') if 'eval' in r]
        self.assertEqual(len(evaluations), 1)
        self.assertIn('--eval-store', evaluations[0])
        self.assertNotIn('--out-link', evaluations[0])
        self.assertFalse(any('--store' in call for call in self.calls('nix-store')))
        self.assertEqual([r['action'] for r in self.retention_requests()], ['realise', 'release'])

    def test_station_busy_full_or_field_mode_falls_back(self):
        self.station_config()
        for scenario in ('busy', 'full', 'field'):
            with self.subTest(scenario=scenario):
                self.assert_ok(self.build('--artifact', 'fit', STATION_HEALTH=scenario))
                self.assertEqual(self.manifests()[-1]['build']['worker'], 'local')

    def test_unconfigured_explicit_station_never_ssh(self):
        result = self.build('--builder', 'station')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('validated', result.stderr)
        self.assertEqual(self.calls('ssh'), [])

    def test_no_local_compatibility_stops_before_compiler(self):
        result = self.build('--builder', 'local', LOCAL_INCOMPATIBLE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any('build' in r for r in self.calls('nix')))

    def test_offline_station_is_explicit_error(self):
        self.station_config()
        result = self.build('--offline', '--builder', 'station')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_invalid_config_does_not_fall_back_to_defaults(self):
        for content in ('{', '[]', '{"policy":{"preferStation":"yes"}}', '{"policy":{"probeTimeoutSeconds":0}}'):
            self.config.write_text(content)
            self.assertNotEqual(self.build('--dry-run').returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_strict_pinned_ssh_and_copy_options(self):
        self.station_config(worker_id='fixture-worker')
        self.assert_ok(self.build('--builder', 'station', '--artifact', 'fit'))
        ssh = self.calls('ssh')[0]
        self.assertIn('StrictHostKeyChecking=yes', ssh)
        self.assertIn('BatchMode=yes', ssh)
        self.assertEqual(ssh[-1], 'crt-platform-builder-health-v1')
        self.assertIn('/dev/null', ssh)
        for call in self.calls('ssh'):
            self.assertIn('StrictHostKeyChecking=yes', call)
            self.assertIn('BatchMode=yes', call)
            self.assertIn('GlobalKnownHostsFile=/dev/null', call)
            self.assertIn('UserKnownHostsFile=' + str(self.base / 'known_hosts'), call)
            self.assertIn(call[-1], ('crt-platform-builder-health-v1', 'crt-platform-builder-retain-v1'))
        import shlex
        imported_options = [shlex.split(json.loads(line))
                            for line in (self.base / 'import-ssh-options').read_text().splitlines()]
        self.assertEqual(len(imported_options), 1)
        self.assertIn('StrictHostKeyChecking=yes', imported_options[0])
        self.assertIn('UserKnownHostsFile=' + str(self.base / 'known_hosts'), imported_options[0])
        download = next(call for call in self.calls('nix-store') if '--realise' in call)
        self.assertEqual(download[download.index('require-sigs') + 1], 'true')
        self.assertEqual(download[download.index('substituters') + 1], 'ssh-ng://builder@station.invalid')

    def test_shim_help_and_stdlib_platform_still_importable(self):
        result = subprocess.run([sys.executable, str(REPO / 'scripts/platform'), '--help'],
                                text=True, capture_output=True, timeout=10)
        self.assert_ok(result)
        self.assertIn('cache-sync', result.stdout)
        result = subprocess.run([sys.executable, '-c', 'import platform; import tools.platform.cli; print(platform.system())'],
                                cwd=REPO, text=True, capture_output=True, timeout=10)
        self.assert_ok(result)


class RetentionCLI(BuildFixture):
    def test_release_follows_successful_import_validity_and_registered_root(self):
        self.station_config(worker_id='fixture-worker')
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'station'))
        requests = self.retention_requests()
        self.assertEqual([r['action'] for r in requests], ['realise', 'release'])
        self.assertEqual({k: v for k, v in requests[0].items() if k != 'action'},
                         {k: v for k, v in requests[1].items() if k != 'action'})
        artifact = self.manifests()[0]['artifacts']['fit']
        self.assertEqual(str(Path(artifact['gcRoot']).readlink()), artifact['storePath'])
        self.assertTrue(artifact['files'])
        for file in artifact['files']:
            self.assertEqual(file['sha256'], hashlib.sha256(Path(file['path']).read_bytes()).hexdigest())
        self.assertEqual(list((self.state / 'transfers').glob('*.json')), [])

    def test_import_validity_and_registration_errors_never_release_or_publish(self):
        for failure in ('COPY_FAIL', 'ROOT_FAIL', 'WRONG_ROOT', 'VALIDITY_FAIL', 'UNREGISTERED_ROOT'):
            with self.subTest(failure=failure):
                self.station_config(worker_id='fixture-worker')
                before = len(self.retention_requests())
                result = self.build('--artifact', 'fit', '--builder', 'station', **{failure: '1'})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual([r['action'] for r in self.retention_requests()[before:]], ['realise'])
                self.assertEqual(self.manifests(), [])
                self.assertTrue(list((self.state / 'transfers').glob('*.json')))
                # Preserve each case's evidence outside the replay queue so the
                # next case exercises its own injected failure independently.
                for journal in (self.state / 'transfers').glob('*.json'):
                    journal.rename(journal.with_suffix('.failed'))

    def test_bad_retention_reply_token_or_path_never_imports_or_releases(self):
        self.station_config(worker_id='fixture-worker')
        for override in ({'token': '../escape'}, {'storePath': '/tmp/untrusted'},
                         {'workerId': 'other-worker'}, {'protocol': True}):
            with self.subTest(override=override):
                result = self.build('--artifact', 'fit', '--builder', 'station',
                                    RETENTION_REPLY_OVERRIDE=json.dumps(override))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.calls('nix-store'))
                self.assertFalse(any(r['action'] == 'release' for r in self.retention_requests()))
                self.assertEqual(self.manifests(), [])
                for journal in (self.state / 'transfers').glob('*.json'):
                    journal.rename(journal.with_suffix('.failed'))

    def test_request_tokens_paths_and_size_are_bounded(self):
        from tools.platform.worker import retention_request
        from tools.platform.runtime import PlatformError
        request = dict(protocol=1, action='realise', workerId='fixture-worker',
                       token='a'*32, drvPath='/nix/store/' + 'a'*32 + '-fixture.drv')
        self.assertEqual(retention_request(json.dumps(request).encode()), request)
        raw = json.dumps(request).encode()
        self.assertEqual(retention_request(raw + b' ' * (4096 - len(raw))), request)
        for change in ({'token': 'a'*31}, {'token': 'a'*33}, {'token': 'A'*32},
                       {'token': '../escape'}, {'drvPath': '/tmp/fixture.drv'},
                       {'drvPath': '/nix/store/' + 'e'*32 + '-fixture.drv'},
                       {'drvPath': '/nix/store/' + 'a'*32 + '-fixture'},
                       {'drvPath': '/nix/store/' + 'a'*32 + '-fixture.drv/../other'},
                       {'gcRoot': '/tmp/caller-root'}):
            with self.subTest(change=change), self.assertRaises(PlatformError):
                retention_request(json.dumps({**request, **change}).encode())
        with self.assertRaises(PlatformError):
            retention_request(b' ' * 4097)

    def test_lost_release_reply_retries_after_local_root_without_worker_rebuild(self):
        self.station_config(worker_id='fixture-worker')
        result = self.build('--artifact', 'fit', '--builder', 'station', RELEASE_LOST_ACK='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('release reply disconnected', result.stderr)
        journal = next((self.state / 'transfers').glob('*.json'))
        original = json.loads(journal.read_text())
        self.assertTrue(Path(original['gcRoot']).is_symlink())
        self.assertEqual(self.manifests(), [])
        self.assert_ok(self.build('--artifact', 'fit', '--builder', 'station'))
        old_requests = [r for r in self.retention_requests() if r['token'] == original['token']]
        self.assertEqual([r['action'] for r in old_requests], ['realise', 'release', 'release'])
        self.assertFalse(journal.exists())
        self.assertTrue(Path(original['gcRoot']).is_symlink())

    def test_pending_worker_transfer_does_not_block_local_build_during_outage(self):
        self.station_config(worker_id='fixture-worker')
        initial=self.build('--artifact','fit','--builder','station',RELEASE_LOST_ACK='1')
        self.assertNotEqual(initial.returncode,0)
        journal=next((self.state/'transfers').glob('*.json'))
        original=json.loads(journal.read_text())
        requests=len(self.retention_requests())
        for builder in ('local','auto'):
            result=self.build('--artifact','fit','--builder',builder,SSH_FAIL='1')
            self.assert_ok(result)
            self.assertIn('deferred',json.loads(result.stdout)['warning'])
            self.assertTrue(journal.exists())
            self.assertTrue(Path(original['gcRoot']).is_symlink())
            self.assertEqual(len(self.retention_requests()),requests)
        self.assertEqual(len(self.manifests()),2)
        self.assertTrue(all(m['build']['worker']=='local' for m in self.manifests()))

    def test_resume_command_recovers_transfer_without_creating_another_release(self):
        self.station_config(worker_id='fixture-worker')
        initial=self.build('--artifact','fit','--builder','station',RELEASE_LOST_ACK='1')
        self.assertNotEqual(initial.returncode,0)
        journal=next((self.state/'transfers').glob('*.json'))
        original=json.loads(journal.read_text())
        realisations=sum(r['action']=='realise' for r in self.retention_requests())
        result=self.run_cli('transfer-resume');self.assert_ok(result)
        self.assertEqual(json.loads(result.stdout)['recovered'],1)
        self.assertFalse(journal.exists())
        self.assertEqual(sum(r['action']=='realise' for r in self.retention_requests()),realisations)
        self.assertEqual(self.manifests(),[])
        self.assertTrue(Path(original['gcRoot']).is_symlink())

    def test_status_and_resume_dry_run_show_transfers_without_contacting_worker(self):
        self.station_config(worker_id='fixture-worker')
        self.build('--artifact','fit','--builder','station',RELEASE_LOST_ACK='1')
        before=self.calls()
        status=self.run_cli('status');self.assert_ok(status)
        self.assertEqual(len(json.loads(status.stdout)['workerTransfers']),1)
        dry=self.run_cli('transfer-resume','--dry-run');self.assert_ok(dry)
        self.assertEqual(len(json.loads(dry.stdout)['pending']),1)
        self.assertEqual(self.calls(),before)
        self.assertTrue(list((self.state/'transfers').glob('*.json')))

    def test_empty_resume_does_not_create_state_or_probe(self):
        result=self.run_cli('transfer-resume');self.assert_ok(result)
        self.assertEqual(json.loads(result.stdout)['recovered'],0)
        self.assertEqual(self.calls(),[])
        self.assertFalse(self.state.exists())

    def test_failed_local_root_sync_prevents_release(self):
        from unittest.mock import patch
        from tools.platform import build
        config = self.station_config(worker_id='fixture-worker')
        store = '/nix/store/' + 'a'*32 + '-fixture'
        root = self.base / 'roots' / 'release' / 'fit'
        root.parent.mkdir(parents=True)
        journal = self.base / 'transfer.json'
        record = dict(protocol=1, action='realise', workerId='fixture-worker', token='a'*32,
                      drvPath=store + '.drv', storePath=store, gcRoot=str(root), station=config['station'])
        journal.write_text(json.dumps(record))
        def successful_local_nix(argv, **kwargs):
            if '--realise' in argv:
                root.symlink_to(store)
                return str(root)
            if '--roots' in argv:
                return f'{root} -> {store}\n'
            self.assertIn('--check-validity', argv)
            return ''
        with patch.object(build, 'run', side_effect=successful_local_nix), \
                patch.object(build, 'sync_dir', side_effect=OSError('root sync interrupted')), \
                patch.object(build, '_retention_rpc') as rpc:
            with self.assertRaisesRegex(OSError, 'root sync interrupted'):
                build.finish_transfer(journal, record, {}, None)
        rpc.assert_not_called()
        self.assertTrue(journal.is_file())
        self.assertTrue(root.is_symlink())

    def test_station_release_roots_and_hashes_each_requested_artifact(self):
        self.station_config(worker_id='fixture-worker')
        self.assert_ok(self.build('--artifact', 'release', '--builder', 'station'))
        artifacts = self.manifests()[0]['artifacts']
        self.assertEqual(set(artifacts), {'sd', 'ospi', 'data'})
        self.assertEqual([r['action'] for r in self.retention_requests()], ['realise', 'release'] * 3)
        for artifact in artifacts.values():
            self.assertEqual(str(Path(artifact['gcRoot']).readlink()), artifact['storePath'])
            self.assertTrue(artifact['files'])
            for file in artifact['files']:
                self.assertEqual(file['sha256'], hashlib.sha256(Path(file['path']).read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
