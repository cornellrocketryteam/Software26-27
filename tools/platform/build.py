"""Existing raw Nix attributes, frozen source, permanent roots, then publication."""
from datetime import datetime, timezone
import os
from pathlib import Path
import uuid
from . import cache
from .builders import select
from .config import endpoint, number, ssh_environment
from .manifest import artifact_files, sha256, snapshot
from .runtime import PlatformError, atomic_json, json_response, run, sync_dir

ARTIFACTS = {'sd': 'sdImage', 'fit': 'fitImage', 'ospi': 'ospiImage', 'data': 'dataCardImage'}


def targets(host, vehicle, artifact, platform):
    if host == 'ground-station':
        return {'system': 'nixosConfigurations.ground-station.config.system.build.toplevel'}
    machine = 'fill-station-liquid' if vehicle == 'liquid' else 'fill-station'
    graph = 'mixosConfigurations' if platform == 'aarch64-linux' else 'mixosBuildConfigurations."x86_64-linux"'
    kinds = ('sd', 'ospi', 'data') if artifact == 'release' else (artifact,)
    return {kind: f'{graph}.{machine}.config.system.build.{ARTIFACTS[kind]}' for kind in kinds}


def nix_options(offline):
    options = ['--no-write-lock-file', '--no-update-lock-file', '--builders', '']
    if offline:
        options += ['--offline', '--option', 'substituters', '', '--option', 'connect-timeout', '3']
    return options


def execute(repo, state, config, args):
    platform = args.build_platform or ('aarch64-linux' if args.host == 'fill-station' else 'x86_64-linux')
    attrs = targets(args.host, args.vehicle, args.artifact, platform)
    if args.dry_run:
        return {'dryRun': True, 'host': args.host, 'platform': platform, 'builder': args.builder,
                'attributes': attrs, 'offline': args.offline, 'outputDirectory': str(repo / 'outputs/platform'),
                'note': 'plan only; no probes, source snapshot, build, or publication performed'}
    worker, reason = select(config, args.builder, platform, args.offline)
    # Retry old items on every normal build; failure cannot invalidate a new local build.
    warning = None
    try:
        cache.sync(state, config, offline=args.offline)
    except PlatformError as exc:
        warning = str(exc)
    release_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex
    state.mkdir(parents=True, exist_ok=True)
    source = snapshot(repo, state / 'sources' / release_id)
    profile = Path(source['snapshot']) / 'fill-station/hardware/profiles' / f'{args.vehicle}.json'
    profile_digest = sha256(profile) if args.host == 'fill-station' else None
    roots = state / 'roots' / release_id
    roots.mkdir(parents=True)
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
        link_options = ['--no-link'] if worker == 'station' else ['--out-link', roots / f'build-{kind}']
        result = json_response(run(['nix', 'build', '--json', *options, *link_options,
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
        if worker == 'station':
            run(['nix', 'copy', '--from', uri, store], env=env,
                timeout=number(config, 'copyTimeoutSeconds', 120, 3600), log=logs / f'{kind}-download.log')
        root = roots / kind
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
                'build': {'platform': platform, 'worker': worker, 'selectionReason': reason,
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
    except PlatformError as exc:
        warning = str(exc)
    return {'releaseId': release_id, 'manifest': str(manifest_path), 'worker': worker, 'reason': reason,
            'publication': 'pending', 'warning': warning}
