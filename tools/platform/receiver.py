"""Fixed SSH receiver: validate, root and durably archive before acknowledging."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from .receipts import MAX_REQUEST, identity, parse_request, validate_receipt
from .runtime import PlatformError, atomic_bytes, atomic_json, durable_mkdir, read_json, run, state_lock, sync_dir


def _archive_barrier(state, release):
    # Repeat even for an existing receipt: a previous process may have died
    # after rename/mkdir but before syncing its containing directory.
    for path in (state / 'archive.json', release / 'manifest.json', release / 'receipt.json'):
        with path.open('rb') as stream:
            os.fsync(stream.fileno())
    for path in (state / 'roots' / release.name, state / 'roots', release,
                 release.parent, state, state.parent):
        sync_dir(path)


def receive(state, archive_id, raw, *, store_dir='/nix/store'):
    identity(archive_id, 'archive ID')
    request, manifest_raw = parse_request(raw, store_dir=store_dir)
    state = Path(state).absolute()
    if '..' in state.parts:
        raise PlatformError('archive state must not contain parent traversal')
    if not state.parent.is_dir():
        raise PlatformError('archive parent directory must already exist')
    for path in request['storePaths']:
        try:
            Path(path).lstat()
        except OSError as exc:
            raise PlatformError(f'imported output missing or unavailable: {path}') from exc
    # Query-only admission, before any realization; unknown paths cannot cause
    # substitution or a build. Derivation paths are rejected by the parser.
    run(['nix', 'path-info', '--offline', '--json', *request['storePaths']], timeout=60)
    durable_mkdir(state)
    with state_lock(state, 'receiver'):
        archive_path = state / 'archive.json'
        archive = {'protocol': 1, 'archiveId': archive_id}
        if archive_path.exists():
            if read_json(archive_path) != archive:
                raise PlatformError('configured archive identity differs from durable archive')
        else:
            atomic_json(archive_path, archive)
        release = state / 'releases' / request['releaseId']
        manifest_path = release / 'manifest.json'
        if manifest_path.exists():
            if manifest_path.read_bytes() != manifest_raw:
                raise PlatformError('duplicate release ID with different manifest')
        else:
            atomic_bytes(manifest_path, manifest_raw)
        roots = {}
        for i, store in enumerate(request['storePaths']):
            root = state / 'roots' / request['releaseId'] / str(i)
            durable_mkdir(root.parent)
            if root.is_symlink():
                if os.readlink(root) != store:
                    raise PlatformError('archive retention root changed; refusing overwrite')
            elif root.exists():
                raise PlatformError('archive retention root is not a symlink')
            # Re-register even an existing link: repairing a missing daemon GC
            # registration must not depend on symlink presence alone.
            run(['nix-store', '--add-root', root, '--indirect', '--realise', store,
                 '--option', 'substitute', 'false', '--option', 'max-jobs', '0',
                 '--option', 'builders', ''], timeout=60)
            if not root.is_symlink() or os.readlink(root) != store:
                raise PlatformError('Nix did not register the expected archive root')
            sync_dir(root.parent)
            roots[store] = str(root)
        # Roots close the GC gap before verifying the complete imported closure.
        # Trust is supplied by this pinned SSH publication protocol, not by a
        # developer-provided signature; content integrity is still mandatory.
        run(['nix', 'store', 'verify', '--offline', '--recursive', '--no-trust',
             *request['storePaths']], timeout=300)
        receipt_path = release / 'receipt.json'
        if receipt_path.exists():
            existing = validate_receipt(read_json(receipt_path), request, archive_id)
            if existing['archivePath'] != str(state) or existing['roots'] != roots:
                raise PlatformError('persisted receipt does not describe this archive location')
            _archive_barrier(state, release)
            return existing
        receipt = {'protocol': 1, 'releaseId': request['releaseId'],
                   'manifestSha256': request['manifestSha256'], 'storePaths': request['storePaths'],
                   'archiveId': archive_id, 'archivePath': str(state), 'roots': roots, 'retained': True,
                   'archivedAt': datetime.now(timezone.utc).isoformat()}
        atomic_json(receipt_path, receipt)
        _archive_barrier(state, release)
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description='Archive one copied release; no build or deployment.')
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--archive-id', required=True)
    args = parser.parse_args(argv)
    try:
        if not args.state_dir.is_absolute():
            raise PlatformError('archive state directory must be absolute')
        raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
        result = receive(args.state_dir, args.archive_id, raw)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (PlatformError, OSError, ValueError) as exc:
        print(f'cache receiver: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
