"""Explicit user JSON; no credentials, generated identities, or implicit station."""
import math
import os
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit
from .runtime import PlatformError, read_json


def state_directory():
    override = os.environ.get('CRT_PLATFORM_STATE_DIR')
    if override:
        return Path(override).expanduser().resolve()
    return (Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))
            / 'cornell-rocketry/platform').expanduser().resolve()


def load_config(path, *, explicit=False):
    if not path.exists() and not explicit:
        return {}
    config = read_json(path)
    if not isinstance(config, dict):
        raise PlatformError('config must be a JSON object')
    for section in ('policy', 'local', 'station', 'cache'):
        if section in config and not isinstance(config[section], dict):
            raise PlatformError(f'config {section} must be an object')
    prefer = config.get('policy', {}).get('preferStation', False)
    if not isinstance(prefer, bool):
        raise PlatformError('policy.preferStation must be boolean')
    for key, default, maximum in (('probeTimeoutSeconds', 10, 60), ('evaluationTimeoutSeconds', 300, 3600),
                                  ('copyTimeoutSeconds', 120, 3600),
                                  ('receiptTimeoutSeconds', 300, 3600),
                                  ('buildTimeoutSeconds', 14400, 86400)):
        number(config, key, default, maximum)
    if 'receiptArchiveId' in config.get('cache', {}):
        from .receipts import identity
        identity(config['cache']['receiptArchiveId'], 'cache receipt archive ID')
    return config


def number(config, key, default, maximum):
    value = config.get('policy', {}).get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
        raise PlatformError(f'policy.{key} must be > 0 and <= {maximum}')
    return value


def endpoint(section):
    """Require an explicit host, pinned known_hosts file, and matching SSH identity."""
    uri = section.get('store', '')
    if not isinstance(uri, str):
        raise PlatformError('store must be an ssh-ng URI')
    try:
        parsed = urlsplit(uri)
        port = parsed.port
    except ValueError as exc:
        raise PlatformError('invalid ssh-ng store URI') from exc
    host = parsed.hostname or ''
    user = parsed.username or ''
    if (parsed.scheme != 'ssh-ng' or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')
            or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*', host)
            or not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_.-]*', user)):
        raise PlatformError('store must be ssh-ng://user@explicit-host[:port], without options/password')
    target = f'{user}@{host}'
    if section.get('sshTarget') != target:
        raise PlatformError('sshTarget must match the ssh-ng store user and host')
    known = section.get('knownHosts')
    if not isinstance(known, str) or not Path(known).is_absolute() or not Path(known).is_file() or not Path(known).stat().st_size:
        raise PlatformError('knownHosts must name an existing nonempty absolute pinned host-key file')
    options = ['-F', '/dev/null', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', f'UserKnownHostsFile={known}', '-o', 'GlobalKnownHostsFile=/dev/null',
               '-o', 'ConnectTimeout=5', '-o', 'ConnectionAttempts=1', '-o', 'ServerAliveInterval=5',
               '-o', 'ServerAliveCountMax=1']
    if port:
        options += ['-p', str(port)]
    return uri.rstrip('/'), target, options


def ssh_environment(options):
    return {**os.environ, 'NIX_SSHOPTS': shlex.join(options)}
