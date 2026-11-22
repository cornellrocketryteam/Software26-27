"""Provision one station-local signing identity; never rotate or export its secret."""
import base64
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

from .runtime import PlatformError, run, sync_dir

ROOT_UID = 0


def controlled(path, *, directory=False, secret=False):
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o022
            or (not directory and info.st_nlink != 1)
            or (secret and stat.S_IMODE(info.st_mode) != 0o600)):
        raise PlatformError('signing material must be root-controlled with restrictive permissions')


def derive(settings, secret, execute):
    try:
        public = execute([settings['nix'], '--extra-experimental-features', 'nix-command',
                          'key', 'convert-secret-to-public'], input_data=secret.read_bytes(), timeout=30).strip()
        name, encoded = public.split(':')
        if name != settings['name'] or len(base64.b64decode(encoded, validate=True)) != 32:
            raise ValueError('invalid public key')
        return public
    except (PlatformError, OSError, ValueError):
        # Nix diagnostics may include malformed input. Never expose them here.
        raise PlatformError('could not validate station signing identity; no key was rotated') from None


def provision(settings, *, execute=run, uid=None):
    if (os.geteuid() if uid is None else uid) != 0:
        raise PlatformError('signing-key provisioning must run as root')
    directory = Path(settings['directory'])
    if not directory.is_absolute() or directory.resolve() != directory or str(directory).startswith('/nix/store'):
        raise PlatformError('signing directory must be an absolute runtime path without symlinks')
    controlled(directory.parent, directory=True)
    directory.mkdir(mode=0o700, exist_ok=True)
    controlled(directory, directory=True)
    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise PlatformError('signing directory must have mode 0700')
    lock = os.open(directory/'.provision.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        controlled(directory/'.provision.lock', secret=True)
        fcntl.flock(lock, fcntl.LOCK_EX)
        secret, public_file = directory/'cache.sec', directory/'cache.pub'
        created = not os.path.lexists(secret)
        if created and os.path.lexists(public_file):
            raise PlatformError('public key exists without its secret; refusing to create a new identity')
        with tempfile.TemporaryDirectory(prefix='.provision-', dir=directory) as temporary:
            temp = Path(temporary)
            if created:
                candidate, generated_public = temp/'cache.sec', temp/'generated.pub'
                try:
                    execute([settings['nixStore'], '--generate-binary-cache-key', settings['name'],
                             str(candidate), str(generated_public)], timeout=30)
                except (PlatformError, OSError):
                    raise PlatformError('station signing-key generation failed; secret diagnostics withheld') from None
                candidate.chmod(0o600)
                controlled(candidate, secret=True)
            else:
                controlled(secret, secret=True)
                candidate = secret
            public = derive(settings, candidate, execute)
            if os.path.lexists(public_file):
                controlled(public_file)
                if public_file.read_text().strip() != public:
                    raise PlatformError('public key does not match existing secret; refusing identity change')
            if created:
                with candidate.open('rb') as stream: os.fsync(stream.fileno())
                os.link(candidate, secret)  # fails rather than overwriting an existing key
                candidate.unlink()
                sync_dir(directory)
            if not public_file.exists():
                pending = temp/'public'
                pending.write_text(public+'\n'); pending.chmod(0o644)
                with pending.open('rb') as stream: os.fsync(stream.fileno())
                os.replace(pending, public_file)
                sync_dir(directory)
        return {'created': created, 'publicKey': public, 'publicKeyFile': str(public_file),
                'privateKeyExported': False}
    finally:
        os.close(lock)


def main(settings_path, argv=None):
    try:
        if (sys.argv[1:] if argv is None else argv):
            raise PlatformError('signing provisioning takes no arguments; identity and paths are fixed')
        result = provision(json.loads(Path(settings_path).read_text()))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (PlatformError, OSError, ValueError) as error:
        print(f'signing provisioning: {error}', file=sys.stderr)
        return 1
