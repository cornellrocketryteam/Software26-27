"""Root-only, fixed-recipe bootstrap check of the normal daemon's cgroup.

This does not validate/enable a worker or change persistent admission settings.
"""
import json
import os
from pathlib import Path
import re
import sys

from .runtime import PlatformError, run

DAEMON = 'unix:///nix/var/nix/daemon-socket/socket'


def maintenance(settings):
    if settings.get('enabled') is not True or settings.get('fieldMode') is not False:
        raise PlatformError('daemon validation requires an enabled maintenance profile')
    marker = Path(settings['fieldMarker'])
    if marker.exists() or marker.is_symlink():
        raise PlatformError('daemon validation inhibited by field mode')
    stats = os.statvfs(settings['storePath'])
    if stats.f_frsize <= 0 or stats.f_bavail < 0 or stats.f_bavail * stats.f_frsize < settings['minimumFreeBytes']:
        raise PlatformError('daemon validation store is below its free-space reserve')


def limits(settings, execute):
    text = execute([settings['systemctl'], 'show', 'nix-daemon.service',
                    '--property=ControlGroup', '--property=ActiveState'], timeout=30)
    values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
    group = values.get('ControlGroup', '')
    if values.get('ActiveState') != 'active' or not group.startswith('/') or group == '/':
        raise PlatformError('Nix daemon must have an active dedicated cgroup')
    if any(part in ('.', '..') for part in group.split('/')):
        raise PlatformError('invalid daemon cgroup path')
    root = Path(settings['cgroupRoot']).resolve()
    path = (root / group.lstrip('/')).resolve()
    if not path.is_relative_to(root):
        raise PlatformError('daemon cgroup escaped the cgroup filesystem')
    try:
        quota, period = (int(value) for value in (path / 'cpu.max').read_text().split())
        memory = int((path / 'memory.max').read_text().strip())
        swap = int((path / 'memory.swap.max').read_text().strip())
        tasks = int((path / 'pids.max').read_text().strip())
    except (OSError, ValueError):
        raise PlatformError('cannot verify finite daemon CPU/memory/task limits') from None
    if not (0 < quota <= 3 * period and period > 0 and 0 < memory <= 6 * 1024**3
            and swap == 0 and 0 < tasks <= 512):
        raise PlatformError('daemon cgroup exceeds validation resource limits')
    return {'path': group, 'cpuQuota': quota, 'cpuPeriod': period,
            'memoryMax': memory, 'memorySwapMax': swap, 'tasksMax': tasks}


def validate(settings, *, execute=run, uid=None):
    if (os.geteuid() if uid is None else uid) != 0:
        raise PlatformError('daemon validation must be run as root')
    maintenance(settings)
    drv = settings.get('fixtureDrv', '')
    if re.fullmatch(r'/nix/store/[0-9abcdfghijklmnpqrsvwxyz]{32}-[A-Za-z0-9+._?=-]+\.drv', drv) is None:
        raise PlatformError('invalid fixed validation derivation')
    nix = [settings['nix'], '--extra-experimental-features', 'nix-command', '--store', DAEMON]
    execute(nix + ['store', 'ping', '--json'], timeout=30)
    before = limits(settings, execute)
    command = nix + ['build', drv + '^*', '--no-link', '--json', '--offline',
                     '--max-jobs', '1', '--cores', '3',
                     '--option', 'pre-build-hook', '', '--option', 'builders', '',
                     '--option', 'substituters', '', '--option', 'substitute', 'false',
                     '--option', 'require-sigs', 'true', '--option', 'flake-registry', '']
    try:
        result = json.loads(execute(command, timeout=300))
        output = Path(result[0]['outputs']['out'])
    except (ValueError, KeyError, IndexError, TypeError):
        raise PlatformError('daemon returned an invalid validation result') from None
    # Always execute the recipe again, even if an old output was present. Its
    # cgroup/user markers are deterministic; cached evidence is insufficient.
    execute(command + ['--rebuild'], timeout=300)
    maintenance(settings)
    after = limits(settings, execute)
    if before != after:
        raise PlatformError('daemon cgroup limits changed during validation')
    try:
        memberships = (output / 'cgroup').read_text().splitlines()
        user = (output / 'user').read_text().strip()
    except OSError:
        raise PlatformError('validation fixture evidence is missing') from None
    expected = before['path']
    groups = [line[3:] for line in memberships if line.startswith('0::')]
    if len(groups) != 1 or not (groups[0] == expected or groups[0].startswith(expected + '/')):
        raise PlatformError('validation build did not run inside the Nix daemon cgroup')
    if user != 'non-root':
        raise PlatformError('validation build did not use an unprivileged build user')
    return {'protocol': 1, 'scope': 'daemon-smoke-validation', 'daemonCgroup': before,
            'fixtureOutput': str(output), 'rebuilt': True, 'workerValidationChanged': False}


def main(settings_path, argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv:
            raise PlatformError('daemon validation takes no arguments; its recipe is fixed')
        settings = json.loads(Path(settings_path).read_text())
        # Do not inherit caller Nix configuration or redirect the store.
        for key in ('NIX_CONFIG', 'NIX_REMOTE', 'NIX_PATH'):
            os.environ.pop(key, None)
        os.environ['NIX_USER_CONF_FILES'] = '/dev/null'
        print(json.dumps(validate(settings), indent=2, sort_keys=True))
        return 0
    except (PlatformError, OSError, ValueError) as error:
        print(f'daemon validation: {error}', file=sys.stderr)
        return 1
