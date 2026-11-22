"""Existing raw Nix attributes, frozen source, permanent roots, then publication."""
from datetime import datetime, timezone
import os
import json
import re
from pathlib import Path
import uuid
import time
from . import cache
from .builders import candidate_pairs, select_pair
from .config import endpoint, number, ssh_environment
from .manifest import artifact_files, sha256, snapshot
from .runtime import PlatformError, atomic_json, durable_mkdir, json_response, read_json, run, state_lock, sync_dir
from .receipts import decode_json
from .worker import RETENTION_BYTES, STORE_NAME, retention_request

ARTIFACTS = {'sd': 'sdImage', 'fit': 'fitImage', 'ospi': 'ospiImage', 'data': 'dataCardImage'}


def targets(host, vehicle, artifact, platform, profile="foundation"):
    if host == 'ground-station':
        name = 'ground-station' if profile == 'foundation' else 'ground-station-' + profile
        return {'system': f'nixosConfigurations.{name}.config.system.build.toplevel'}
    machine = 'fill-station-liquid' if vehicle == 'liquid' else 'fill-station'
    graph = 'mixosConfigurations' if platform == 'aarch64-linux' else 'mixosBuildConfigurations."x86_64-linux"'
    kinds = ('sd', 'ospi', 'data') if artifact == 'release' else (artifact,)
    return {kind: f'{graph}.{machine}.config.system.build.{ARTIFACTS[kind]}' for kind in kinds}


def nix_options(offline):
    options = ['--no-write-lock-file', '--no-update-lock-file', '--builders', '']
    if offline:
        options += ['--offline', '--option', 'substituters', '', '--option', 'connect-timeout', '3']
    return options


RETENTION_COMMAND = 'crt-platform-builder-retain-v1'


def _retention_rpc(station, request, timeout, log=None):
    wire = json.dumps(request).encode()
    retention_request(wire)
    _, target, options = endpoint(station)
    raw = run(['ssh', *options, target, RETENTION_COMMAND], input_data=wire, timeout=timeout, log=log)
    if len(raw.encode()) > RETENTION_BYTES:
        raise PlatformError('retention response exceeds 4096 bytes')
    reply = decode_json(raw, 'retention response')
    response_fields = {'retained', 'storePath'} if request['action'] == 'realise' else {'released'}
    if (not isinstance(reply, dict) or set(reply) != set(request) | response_fields
            or type(reply.get('protocol')) is not int
            or any(reply.get(k) != v for k, v in request.items())):
        raise PlatformError('retention response identity mismatch')
    if request['action'] == 'realise':
        store = reply.get('storePath')
        if (reply.get('retained') is not True or not isinstance(store, str)
                or not re.fullmatch(STORE_NAME, store) or store.endswith('.drv')):
            raise PlatformError('retention response has invalid output or no root acknowledgement')
    elif reply.get('released') is not True:
        raise PlatformError('retention release not acknowledged')
    return reply


def finish_transfer(journal, record, config, log):
    station = record['station']
    uri, _, options = endpoint(station)
    root = Path(record['gcRoot'])
    store = record['storePath']
    durable_mkdir(root.parent)
    # Realization's temporary roots cover substitution/import until the indirect
    # permanent root is registered. A separate `nix copy` leaves a GC race here.
    run(['nix-store', '--realise', store, '--add-root', root, '--indirect',
         '--option', 'substituters', uri, '--option', 'builders', '',
         '--option', 'require-sigs', 'true'], env=ssh_environment(options),
        timeout=number(config, 'copyTimeoutSeconds', 120, 3600), log=log)
    if not root.is_symlink() or os.readlink(root) != store:
        raise PlatformError('local retention root does not match downloaded output')
    run(['nix-store', '--check-validity', store],
        timeout=number(config, 'probeTimeoutSeconds', 10, 60))
    registered = run(['nix-store', '--query', '--roots', store],
                     timeout=number(config, 'probeTimeoutSeconds', 10, 60)).splitlines()
    if str(root) not in registered and f'{root} -> {store}' not in registered:
        raise PlatformError('local retention root is not registered with Nix')
    sync_dir(root.parent)
    sync_dir(root.parent.parent)
    request = {k: record[k] for k in ('protocol', 'workerId', 'token', 'drvPath')}
    request['action'] = 'release'
    _retention_rpc(station, request, number(config, 'probeTimeoutSeconds', 10, 60), log)
    Path(journal).unlink()
    sync_dir(Path(journal).parent)


def recover_transfers(state, config):
    # Serialize transfer replay against new builds sharing this state directory.
    # This also prevents a stale replay from recreating a released worker root.
    for journal in sorted((state / 'transfers').glob('*.json')):
        record = read_json(journal)
        request = {k: record[k] for k in ('protocol', 'action', 'workerId', 'token', 'drvPath')}
        retention_request(json.dumps(request).encode())
        if 'storePath' not in record:
            reply = _retention_rpc(record['station'], request,
                                   number(config, 'buildTimeoutSeconds', 14400, 86400))
            record['storePath'] = reply['storePath']
            atomic_json(journal, record)
        finish_transfer(journal, record, config, None)


def transfer_status(state):
    """Read persisted transfer metadata without RPCs or filesystem mutations."""
    records = []
    for path in sorted((state / 'transfers').glob('*.json')):
        record = read_json(path)
        if not isinstance(record, dict):
            raise PlatformError(f'invalid worker transfer journal: {path}')
        records.append({'journal': str(path), 'workerId': record.get('workerId'),
                        'token': record.get('token'), 'drvPath': record.get('drvPath'),
                        'storePath': record.get('storePath'), 'gcRoot': record.get('gcRoot'),
                        'phase': 'output-known' if 'storePath' in record else 'realisation-reply-pending'})
    return records


def resume_transfers(state, config):
    if not state.exists():
        return {'recovered': 0, 'pending': []}
    with state_lock(state, name='worker-transfers'):
        before = transfer_status(state)
        recover_transfers(state, config)
        pending = transfer_status(state)
    return {'recovered': len(before) - len(pending), 'pending': pending}


def execute(repo, state, config, args):
    if args.dry_run:
        return _execute(repo, state, config, args)
    durable_mkdir(state)
    with state_lock(state, name='worker-transfers'):
        return _execute(repo, state, config, args)


def _execute(repo, state, config, args):
    started = time.monotonic()
    candidates = candidate_pairs(config, args.builder, args.build_platform, args.offline, args.host)
    if args.dry_run:
        planned_platform = candidates[0][1]
        attrs = targets(args.host, args.vehicle, args.artifact, planned_platform, getattr(args, "profile", "foundation"))
        return {'dryRun': True, 'host': args.host, 'platform': planned_platform, 'builder': args.builder,
                'attributes': attrs, 'offline': args.offline, 'outputDirectory': str(repo / 'outputs/platform'),
                'routingCandidates': [{'worker': worker, 'platform': platform,
                    'attributes': targets(args.host, args.vehicle, args.artifact, platform, getattr(args, "profile", "foundation"))}
                    for worker, platform in candidates],
                'note': 'planned preference only; no probes, source snapshot, build, or publication performed'}
    worker, platform, reason = select_pair(config, args.builder, args.build_platform, args.offline, args.host)
    attrs = targets(args.host, args.vehicle, args.artifact, platform, getattr(args, "profile", "foundation"))
    if worker == 'station' and not config['station'].get('workerId'):
        raise PlatformError('station retention requires an explicit pinned workerId')
    # A failed station must not turn retained remote transfers into a dependency
    # of new local work. Keep those journals/roots and retry on a station build.
    warning = None
    if worker == 'station':
        recover_transfers(state, config)
    else:
        pending = len(list((state / 'transfers').glob('*.json')))
        if pending:
            warning = f'{pending} worker transfer(s) deferred; journals/roots retained for a later station build'
    # Cache publication is independent of the chosen execution worker.
    try:
        cache.sync(state, config, offline=args.offline)
    except (PlatformError, OSError) as exc:
        warning = '; '.join(filter(None, [warning, str(exc)]))
    release_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex
    state.mkdir(parents=True, exist_ok=True)
    source = snapshot(repo, state / 'sources' / release_id)
    profile = Path(source['snapshot']) / 'fill-station/hardware/profiles' / f'{args.vehicle}.json'
    profile_digest = sha256(profile) if args.host == 'fill-station' else None
    roots = state / 'roots' / release_id
    durable_mkdir(roots)
    logs = state / 'logs' / release_id
    logs.mkdir(parents=True)
    options = nix_options(args.offline)
    env = None
    if worker == 'station':
        uri, _, ssh_options = endpoint(config['station'])
        options += ['--store', uri]
        env = ssh_environment(ssh_options)
    timeout = number(config, 'probeTimeoutSeconds', 10, 60)
    # Evaluate every requested target first. A bad/missing attr or missing locked input is not failover.
    run(['nix', 'build', '--dry-run', '--json', *options,
         *[f'path:{source["snapshot"]}#{attr}' for attr in attrs.values()]],
        timeout=number(config, 'evaluationTimeoutSeconds', 300, 3600), env=env,
        log=logs / 'preflight.log')
    output = repo / 'outputs/platform' / release_id
    output.mkdir(parents=True)
    artifacts = {}
    for kind, attr in attrs.items():
        root = roots / kind
        if worker == 'station':
            # Evaluate into the remote store; this does not realize the output.
            drv = run(['nix', 'eval', '--raw', *options, '--eval-store', uri,
                       f'path:{source["snapshot"]}#{attr}.drvPath'], env=env,
                      timeout=number(config, 'evaluationTimeoutSeconds', 300, 3600),
                      log=logs / f'{kind}-evaluate.log').strip()
            request = {'protocol': 1, 'action': 'realise', 'workerId': config['station']['workerId'],
                       'token': uuid.uuid4().hex, 'drvPath': drv}
            retention_request(json.dumps(request).encode())
            journal = state / 'transfers' / f'{request["token"]}.json'
            record = {**request, 'station': config['station'], 'gcRoot': str(root)}
            # Persist the token BEFORE sending: a lost reply is replayable.
            atomic_json(journal, record)
            reply = _retention_rpc(config['station'], request,
                                   number(config, 'buildTimeoutSeconds', 14400, 86400),
                                   logs / f'{kind}.log')
            store = reply['storePath']
            record['storePath'] = store
            atomic_json(journal, record)
            finish_transfer(journal, record, config, logs / f'{kind}-download.log')
        else:
            result = json_response(run(['nix', 'build', '--json', *options,
                                        '--out-link', roots / f'build-{kind}',
                                        f'path:{source["snapshot"]}#{attr}'], env=env,
                                       timeout=number(config, 'buildTimeoutSeconds', 14400, 86400),
                                       log=logs / f'{kind}.log'), 'Nix build')
            try:
                store = result[0]['outputs']['out']
                drv = result[0]['drvPath']
            except (KeyError, IndexError, TypeError) as exc:
                raise PlatformError('Nix build did not return a single out path') from exc
            if not isinstance(store, str) or not Path(store).is_absolute():
                raise PlatformError('Nix build returned invalid output path')
            run(['nix-store', '--add-root', root, '--indirect', '--realise', store], timeout=timeout,
                log=logs / f'{kind}-root.log')
            if not root.is_symlink() or root.resolve() != Path(store).resolve():
                raise PlatformError(f'nix-store did not establish expected GC root: {root}')
            sync_dir(roots)
        files = artifact_files(store)
        (output / kind).symlink_to(store)
        artifacts[kind] = {'attribute': attr, 'drvPath': drv, 'storePath': store,
                           'outputPath': str(output / kind), 'gcRoot': str(root), 'files': files,
                           'sizeBytes': sum(f['sizeBytes'] for f in files)}
    manifest = {'schemaVersion': 1, 'releaseId': release_id, 'createdAt': datetime.now(timezone.utc).isoformat(),
                'host': args.host, 'vehicle': args.vehicle, 'source': source, 'profileSha256': profile_digest,
                'classification': 'development' if source['dirty'] else 'candidate',
                'build': {'platform': platform, 'requestedPlatform': args.build_platform, 'worker': worker,
                          'workerId': config['station'].get('workerId') if worker == 'station' else None,
                          'selectionReason': reason,
                          'elapsedSecondsBeforePublication': time.monotonic() - started,
                          'offline': args.offline, 'logDirectory': str(logs)},
                'artifacts': artifacts, 'bootloaderVersion': None, 'tests': [],
                'publication': {'state': 'pending', 'statusSource': str(state / 'outbox' / f'{release_id}.json')},
                'deployment': {'state': 'not-deployed'}, 'preparedInputsRetained': False}
    # Durable authoritative manifest lives with state, not the disposable output links.
    manifest_path = state / 'releases' / release_id / 'manifest.json'
    atomic_json(manifest_path, manifest)
    (output / 'manifest.json').symlink_to(manifest_path)
    sync_dir(output)
    cache.enqueue(state, manifest_path, manifest)
    try:
        cache.sync(state, config, offline=args.offline, release_ids={release_id})
    except (PlatformError, OSError) as exc:
        warning = '; '.join(filter(None, [warning, str(exc)]))
    return {'releaseId': release_id, 'manifest': str(manifest_path), 'worker': worker, 'reason': reason,
            'publication': cache.publication(state, release_id), 'warning': warning}
