"""Versioned bounded receipt wire protocol; exact manifest bytes identify a release."""
import base64
import hashlib
import json
from pathlib import Path
import re

from .runtime import PlatformError

MAX_MANIFEST = 1024 * 1024
MAX_REQUEST = 2 * 1024 * 1024


def identity(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value):
        raise PlatformError(f'invalid {label}')
    return value


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def decode_json(raw, label):
    try:
        return json.loads(raw, object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PlatformError(f'{label}: invalid JSON') from exc


def request_bytes(record):
    with Path(record['manifest']).open('rb') as stream:
        raw = stream.read(MAX_MANIFEST + 1)
    if len(raw) > MAX_MANIFEST:
        raise PlatformError('manifest exceeds 1 MiB receipt limit')
    digest = hashlib.sha256(raw).hexdigest()
    if digest != record['manifestSha256']:
        raise PlatformError('manifest digest changed; refusing receipt request')
    return json.dumps({'protocol': 1, 'releaseId': record['releaseId'],
                       'manifestSha256': digest, 'storePaths': record['storePaths'],
                       'manifestBase64': base64.b64encode(raw).decode('ascii')}).encode()


def parse_request(raw, *, store_dir='/nix/store'):
    if len(raw) > MAX_REQUEST:
        raise PlatformError('receipt request exceeds 2 MiB')
    request = decode_json(raw, 'receipt request')
    if not isinstance(request, dict) or type(request.get('protocol')) is not int or request['protocol'] != 1:
        raise PlatformError('unsupported receipt request protocol')
    release_id = identity(request.get('releaseId'), 'release ID')
    digest = request.get('manifestSha256')
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise PlatformError('invalid manifest digest')
    try:
        manifest_raw = base64.b64decode(request['manifestBase64'], validate=True)
    except (ValueError, TypeError, KeyError) as exc:
        raise PlatformError('invalid base64 manifest') from exc
    if len(manifest_raw) > MAX_MANIFEST or hashlib.sha256(manifest_raw).hexdigest() != digest:
        raise PlatformError('manifest digest mismatch or oversized manifest')
    manifest = decode_json(manifest_raw, 'manifest')
    if (not isinstance(manifest, dict) or type(manifest.get('schemaVersion')) is not int
            or manifest['schemaVersion'] != 1 or manifest.get('releaseId') != release_id
            or not isinstance(manifest.get('artifacts'), dict) or not 0 < len(manifest['artifacts']) <= 64):
        raise PlatformError('invalid release manifest identity/artifacts')
    paths = request.get('storePaths')
    if (not isinstance(paths, list) or not 0 < len(paths) <= 64
            or not all(isinstance(p, str) for p in paths) or paths != sorted(set(paths))):
        raise PlatformError('store paths must be a nonempty sorted unique list')
    for path in paths:
        p = Path(path)
        if (str(p.parent) != store_dir or str(p) != path
                or p.name.endswith('.drv')
                or not re.fullmatch(r'[0123456789abcdfghijklmnpqrsvwxyz]{32}-[A-Za-z0-9+._?=-]{1,178}', p.name)):
            raise PlatformError('receipt accepts only top-level Nix output paths, never derivations')
    try:
        declared = sorted({a['storePath'] for a in manifest['artifacts'].values()})
    except (KeyError, TypeError) as exc:
        raise PlatformError('invalid artifact store paths') from exc
    if paths != declared:
        raise PlatformError('request store paths disagree with manifest')
    return request, manifest_raw


def validate_receipt(receipt, record, archive_id):
    identity(archive_id, 'archive ID')
    if (not isinstance(receipt, dict) or type(receipt.get('protocol')) is not int
            or receipt['protocol'] != 1 or receipt.get('retained') is not True
            or receipt.get('archiveId') != archive_id
            or receipt.get('releaseId') != record['releaseId']
            or receipt.get('manifestSha256') != record['manifestSha256']
            or receipt.get('storePaths') != record['storePaths']):
        raise PlatformError('receipt identity/digest/paths do not match this publication')
    archive = receipt.get('archivePath')
    if (not isinstance(archive, str) or not archive.startswith('/') or str(Path(archive)) != archive
            or '..' in Path(archive).parts or any(ord(c) < 32 for c in archive)):
        raise PlatformError('receipt has invalid archive path')
    expected = {path: str(Path(archive) / 'roots' / record['releaseId'] / str(i))
                for i, path in enumerate(record['storePaths'])}
    if receipt.get('roots') != expected:
        raise PlatformError('receipt retention roots do not match store paths')
    return receipt
