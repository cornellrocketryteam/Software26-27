"""Durable outbox. Copy is not a receipt; keep all pins until a receiver exists."""
from pathlib import Path
from .config import endpoint, number, ssh_environment
from .runtime import PlatformError, atomic_json, read_json, run, state_lock


def _new_record(manifest_path, manifest):
    from .manifest import sha256
    try:
        return {'version': 1, 'releaseId': manifest['releaseId'], 'state': 'pending',
                'manifest': str(manifest_path), 'manifestSha256': sha256(manifest_path),
                'storePaths': sorted({a['storePath'] for a in manifest['artifacts'].values()}),
                'gcRoots': [a['gcRoot'] for a in manifest['artifacts'].values()],
                'attempts': 0, 'reason': 'cache not configured; locally retained'}
    except (KeyError, TypeError) as exc:
        raise PlatformError(f'invalid release manifest: {manifest_path}') from exc


def enqueue(state, manifest_path, manifest):
    record = _new_record(manifest_path, manifest)
    with state_lock(state):
        path = state / 'outbox' / f'{manifest["releaseId"]}.json'
        if path.exists():
            # A concurrent sync may already have recovered the durable manifest.
            existing = read_json(path)
            if existing.get('manifestSha256') == record['manifestSha256']:
                return
            raise PlatformError(f'duplicate release ID with different manifest: {manifest["releaseId"]}')
        atomic_json(path, record)


def _recover(state):
    """Manifest is the write-ahead record. Caller owns the short outbox lock."""
    for manifest_path in sorted((state / 'releases').glob('*/manifest.json')):
        release_id = manifest_path.parent.name
        path = state / 'outbox' / f'{release_id}.json'
        if path.exists():
            continue
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict) or manifest.get('schemaVersion') != 1 or manifest.get('releaseId') != release_id:
            raise PlatformError(f'invalid release manifest: {manifest_path}')
        atomic_json(path, _new_record(manifest_path, manifest))


def _records(state):
    records = []
    for path in sorted((state / 'outbox').glob('*.json')):
        record = read_json(path)
        if (not isinstance(record, dict) or record.get('version') != 1 or record.get('state') != 'pending'
                or record.get('releaseId') != path.stem or not isinstance(record.get('storePaths'), list)
                or not record['storePaths'] or not all(isinstance(p, str) and Path(p).is_absolute() for p in record['storePaths'])
                or not isinstance(record.get('gcRoots'), list)
                or not record['gcRoots'] or not all(isinstance(p, str) and Path(p).is_absolute() for p in record['gcRoots'])
                or not isinstance(record.get('attempts'), int) or isinstance(record['attempts'], bool)
                or record['attempts'] < 0 or not isinstance(record.get('manifest'), str)
                or not isinstance(record.get('manifestSha256'), str)):
            raise PlatformError(f'invalid outbox record: {path}')
        records.append((path, record))
    return records


def _validate_for_copy(record):
    from .manifest import sha256
    if sha256(record['manifest']) != record['manifestSha256']:
        raise PlatformError('manifest digest changed; refusing publication')
    manifest = read_json(record['manifest'])
    expected = _new_record(record['manifest'], manifest)
    if any(record[k] != expected[k] for k in ('releaseId', 'storePaths', 'gcRoots')):
        raise PlatformError('outbox paths disagree with manifest; refusing publication')
    for artifact in manifest['artifacts'].values():
        root = Path(artifact['gcRoot'])
        if not root.is_symlink() or not root.exists() or root.resolve() != Path(artifact['storePath']).resolve():
            raise PlatformError('local GC root missing or changed; refusing publication')


def sync(state, config, *, offline=False, release_ids=None):
    if not state.exists():
        return []
    # Lock order is sync -> outbox. Network I/O never holds the outbox lock,
    # so another successful build can always durably enqueue while copy is slow.
    with state_lock(state, 'cache-sync'):
        with state_lock(state):
            _recover(state)
            records = _records(state)
        for path, record in records:
            if release_ids is not None and record['releaseId'] not in release_ids:
                continue
            if offline:
                record['reason'] = 'offline; publication deferred'
            elif not config.get('cache'):
                record['reason'] = 'cache not configured; locally retained'
            else:
                try:
                    _validate_for_copy(record)
                    uri, _, options = endpoint(config['cache'])
                    record['attempts'] += 1
                    run(['nix', 'copy', '--to', uri, *record['storePaths']],
                        timeout=number(config, 'copyTimeoutSeconds', 120, 3600), env=ssh_environment(options))
                    record['reason'] = 'copy complete; validated durable remote receipt required (receiver not implemented)'
                except (PlatformError, OSError) as exc:
                    record['reason'] = str(exc)
            with state_lock(state):
                atomic_json(path, record)
        return [record for _, record in records]


def status(state):
    # Atomic rename makes read-only status safe without creating a lock/state directory.
    return [record for _, record in _records(state)]
