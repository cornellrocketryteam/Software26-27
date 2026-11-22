"""Prepare a PC-owned deployment identity with an operator-verified host pin."""
import base64
import ipaddress
import os
from pathlib import Path
import re
import struct
import tempfile

from .runtime import PlatformError, atomic_bytes, run, state_lock

BEGIN = '# BEGIN CRT fillstation-deploy\n'
END = '# END CRT fillstation-deploy\n'


def regular(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise PlatformError(f'refusing non-regular file: {path}')
    if path.exists() and path.stat().st_uid != os.getuid():
        raise PlatformError(f'file is not owned by current user: {path}')


def host_public(path):
    text = path.read_text()
    lines = text.strip().splitlines()
    if len(lines) != 1 or len(text) > 4096:
        raise PlatformError('supply one verified ED25519 public host key, not a known_hosts file')
    fields = lines[0].split()
    if len(fields) < 2 or fields[0] != 'ssh-ed25519':
        raise PlatformError('host key must be ssh-ed25519')
    try:
        blob = base64.b64decode(fields[1], validate=True)
    except ValueError as exc:
        raise PlatformError('invalid host key encoding') from exc
    if blob[:4] != struct.pack('>I', 11) or blob[4:15] != b'ssh-ed25519' or blob[15:19] != struct.pack('>I', 32) or len(blob) != 51:
        raise PlatformError('invalid ED25519 host key')
    return ' '.join(fields[:2])


def quoted(path):
    value = str(path)
    if any(c in value for c in '\n\r%'):
        raise PlatformError('SSH paths cannot contain newlines or percent expansions')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def execute(args):
    host = str(ipaddress.IPv4Address(args.host))
    public_host = host_public(args.host_key)
    ssh = Path.home()/'.ssh'
    if ssh.is_symlink() or (ssh.exists() and (not ssh.is_dir() or ssh.stat().st_uid != os.getuid())):
        raise PlatformError('SSH directory must be a directory owned by current user, not a symlink')
    config, key, pins = ssh/'config', ssh/'fill-station-deploy_ed25519', ssh/'fill-station-deploy_known_hosts'
    pub = Path(str(key)+'.pub')
    for path in (config, key, pub, pins):
        regular(path)
    # Validate paths even in dry-run, before creating anything.
    for path in (key, pins):
        quoted(path)
    original = config.read_text() if config.exists() else ''
    old = original
    if BEGIN in old or END in old:
        if not old.startswith(BEGIN) or old.count(BEGIN) != 1 or old.count(END) != 1:
            raise PlatformError('managed SSH block was edited/moved; inspect manually')
        old = old.split(END, 1)[1]
    if re.search(r'^\s*Host\s+[^\n]*\bfillstation-deploy\b', old, re.I | re.M):
        raise PlatformError('unmanaged fillstation-deploy alias already exists; inspect manually')
    pin = f'{host} {public_host}\n'
    if pins.exists() and pins.read_text() != pin:
        raise PlatformError('existing host pin differs; verify rotation manually, nothing replaced')
    if pub.exists() and not key.exists():
        raise PlatformError('public deployment key exists without private key; inspect manually')
    result = {'alias': 'fillstation-deploy', 'host': host, 'identityFile': str(key),
              'hostKeyFile': str(pins), 'dryRun': args.dry_run, 'boardEnrolled': False,
              'networkContacted': False, 'nextStep': 'enroll publicKey on board, then test fresh SSH without an agent'}
    if args.dry_run:
        return result
    ssh.mkdir(mode=0o700, exist_ok=True)
    ssh.chmod(0o700)
    with state_lock(ssh, 'crt-deploy-setup'):
        # Serialize setup; reject a concurrent change rather than overwrite it.
        for path in (config, key, pub, pins):
            regular(path)
        if (config.read_text() if config.exists() else '') != original:
            raise PlatformError('SSH configuration changed; rerun setup')
        if pins.exists() and pins.read_text() != pin:
            raise PlatformError('host pin changed; inspect manually')
        if not key.exists():
            with tempfile.TemporaryDirectory(prefix='.crt-deploy-', dir=ssh) as directory:
                fresh = Path(directory)/'key'
                run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'ground-station-fill-deploy', '-f', fresh])
                # Hard-link creation refuses to overwrite an existing identity.
                os.link(fresh, key)
        key.chmod(0o600)
        public_key = run(['ssh-keygen', '-y', '-P', '', '-f', key]).strip()
        if pub.exists() and pub.read_text().split()[:2] != public_key.split()[:2]:
            raise PlatformError('deployment public/private keys do not match')
        atomic_bytes(pub, (public_key+' ground-station-fill-deploy\n').encode())
        atomic_bytes(pins, pin.encode())
        block = (BEGIN + 'Host fillstation-deploy\n' + f'  HostName {host}\n  User root\n'
                 + f'  IdentityFile {quoted(key)}\n  UserKnownHostsFile {quoted(pins)}\n'
                 + '  GlobalKnownHostsFile /dev/null\n  HostKeyAlgorithms ssh-ed25519\n'
                 + '  IdentitiesOnly yes\n  IdentityAgent none\n  ForwardAgent no\n'
                 + '  StrictHostKeyChecking yes\n  UpdateHostKeys no\n  BatchMode yes\n  ConnectTimeout 5\n'
                 + 'Host *\n' + END)
        atomic_bytes(config, (block+old).encode())
        result['publicKey'] = public_key+' ground-station-fill-deploy'
        return result
