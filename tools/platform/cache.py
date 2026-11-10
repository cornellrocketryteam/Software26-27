"""Durable publication state. Only a matching remote receipt acknowledges a copy."""
from datetime import datetime, timezone
from pathlib import Path
from .config import endpoint, number, ssh_environment
from .receipts import MAX_REQUEST, decode_json, request_bytes, validate_receipt
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
        if (not isinstance(record, dict) or record.get('version') != 1 or record.get('state') not in ('pending', 'acknowledged')
                or record.get('releaseId') != path.stem or not isinstance(record.get('storePaths'), list)
                or not record['storePaths'] or not all(isinstance(p, str) and Path(p).is_absolute() for p in record['storePaths'])
                or not isinstance(record.get('gcRoots'), list)
                or not record['gcRoots'] or not all(isinstance(p, str) and Path(p).is_absolute() for p in record['gcRoots'])
                or not isinstance(record.get('attempts'), int) or isinstance(record['attempts'], bool)
                or record['attempts'] < 0 or not isinstance(record.get('manifest'), str)
                or not isinstance(record.get('manifestSha256'), str)):
            raise PlatformError(f'invalid outbox record: {path}')
        if record['state'] == 'acknowledged':
            validate_receipt(record.get('receipt'), record, record.get('receiptArchiveId'))
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
            if record['state'] == 'acknowledged':
                continue
            if release_ids is not None and record['releaseId'] not in release_ids:
                continue
            if offline:
                record['reason'] = 'offline; publication deferred'
            elif not config.get('cache'):
                record['reason'] = 'cache not configured; locally retained'
            else:
                try:
                    _validate_for_copy(record)
                    uri, target, options = endpoint(config['cache'])
                    record['attempts'] += 1
                    run(['nix', 'copy', '--to', uri, *record['storePaths']],
                        timeout=number(config, 'copyTimeoutSeconds', 120, 3600), env=ssh_environment(options))
                    archive_id = config['cache'].get('receiptArchiveId')
                    if archive_id is None:
                        record['reason'] = 'copy complete; receiptArchiveId not configured; retention unacknowledged'
                    else:
                        response = run(['ssh', *options, '--', target, 'crt-platform-cache-receive-v1'],
                                       input_data=request_bytes(record),
                                       timeout=number(config, 'receiptTimeoutSeconds', 300, 3600))
                        if len(response) > MAX_REQUEST:
                            raise PlatformError('receipt response exceeds 2 MiB')
                        receipt = validate_receipt(decode_json(response, 'receipt'), record, archive_id)
                        record.update(state='acknowledged', receipt=receipt, receiptArchiveId=archive_id,
                                      cacheStore=uri, acknowledgedAt=datetime.now(timezone.utc).isoformat(),
                                      reason=f'retained by archive {archive_id}; local release roots retained')
                except (PlatformError, OSError) as exc:
                    record['reason'] = str(exc)
            with state_lock(state):
                atomic_json(path, record)
        return [record for _, record in records if record['state'] == 'pending']


def status(state):
    # Atomic rename makes read-only status safe without creating a lock/state directory.
    return [record for _, record in _records(state) if record['state'] == 'pending']


def acknowledged(state):
    return [record for _, record in _records(state) if record['state'] == 'acknowledged']


def publication(state, release_id):
    # A damaged older queue entry is surfaced as the build's sync warning; it
    # must not invalidate a newly built and durably enqueued release.
    record = read_json(state / 'outbox' / f'{release_id}.json')
    if (not isinstance(record, dict) or record.get('releaseId') != release_id
            or record.get('state') not in ('pending', 'acknowledged')):
        raise PlatformError('invalid publication record for completed build')
    if record['state'] == 'acknowledged':
        validate_receipt(record.get('receipt'), record, record.get('receiptArchiveId'))
    return record['state']
