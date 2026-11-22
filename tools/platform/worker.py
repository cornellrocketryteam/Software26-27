"""Runtime worker health, guarded SSH stdio and independent derivation admission."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import tempfile

from .runtime import PlatformError, atomic_json, json_response, read_json, run, sync_dir

DAEMON_STORE = 'unix:///nix/var/nix/daemon-socket/socket'
SYSTEMS = ('x86_64-linux', 'aarch64-linux')


def load_policy(path):
    policy = read_json(path)
    if not isinstance(policy, dict) or type(policy.get('protocol')) is not int or policy['protocol'] != 1:
        raise PlatformError('unsupported worker policy protocol')
    for key in ('enabled', 'validated', 'remoteEnabled', 'fieldMode'):
        if type(policy.get(key)) is not bool:
            raise PlatformError(f'worker policy {key} must be boolean')
    for key, maximum in (('minimumFreeBytes', 2**63-1), ('sessionTimeoutSeconds', 86400)):
        if type(policy.get(key)) is not int or not 0 < policy[key] <= maximum:
            raise PlatformError(f'worker policy {key} must be a positive integer <= {maximum}')
    platforms = policy.get('platforms')
    if (not isinstance(platforms, list) or not all(isinstance(p, str) and p in SYSTEMS for p in platforms)
            or len(platforms) != len(set(platforms))):
        raise PlatformError('worker policy platforms must be distinct supported build systems')
    if 'workerId' not in policy:
        raise PlatformError('worker policy workerId is required (nullable when unconfigured)')
    worker_id = policy['workerId']
    if worker_id is not None and (not isinstance(worker_id, str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', worker_id)):
        raise PlatformError('invalid worker identity')
    return policy


def _field_mode(policy, marker):
    if policy['fieldMode']:
        return True
    try:
        Path(marker).lstat()
        return True
    except FileNotFoundError:
        return False
    # Other errors propagate: unreadable state must never mean maintenance.


def _free_bytes(path):
    stats = os.statvfs(path)
    if stats.f_bavail < 0 or stats.f_frsize <= 0:
        raise PlatformError('cannot determine usable store free space')
    return stats.f_bavail * stats.f_frsize


def admit(policy, *, field_marker, store_path):
    """No daemon calls or session lock: safe to invoke inside pre-build-hook."""
    if not policy['enabled'] or not policy['validated']:
        raise PlatformError('station builds disabled or unvalidated')
    if _field_mode(policy, field_marker):
        raise PlatformError('station builds inhibited by field mode')
    free = _free_bytes(store_path)
    if free < policy['minimumFreeBytes']:
        raise PlatformError('store filesystem below free-space reserve')
    return free


@contextmanager
def _session_lock(path):
    # The NixOS module creates the root-controlled file; never create, unlink
    # or follow a peer-replaceable lock. The containing directory is not writable
    # by the build account, so all sessions lock the same inode.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PlatformError('worker busy: another remote session holds admission') from exc
        yield fd
    finally:
        os.close(fd)


def _active_arm_binfmt(root):
    try:
        with (Path(root) / 'aarch64-linux').open() as stream:
            text = stream.read(4097)
        lines = text.splitlines()
        if len(text) > 4096 or not lines or lines[0] != 'enabled':
            return False
        fields = {line.split(' ', 1)[0].rstrip(':'): line.split(' ', 1)[1].strip()
                  for line in lines[1:] if ' ' in line}
        interpreter = fields.get('interpreter', '')
        return ('F' in fields.get('flags', '') and interpreter.startswith('/')
                and os.access(interpreter, os.X_OK))
    except OSError:
        return False


def _runtime_platforms(policy, binfmt_root):
    ping = json_response(run(['nix', 'store', 'ping', '--json', '--store', DAEMON_STORE], timeout=3), 'daemon ping')
    if not isinstance(ping, dict):
        raise PlatformError('invalid daemon ping response')
    settings = json_response(run(['nix', 'config', 'show', '--json'], timeout=3), 'worker Nix settings')
    if not isinstance(settings, dict):
        raise PlatformError('invalid worker Nix settings')
    native = settings.get('system', {})
    extras = settings.get('extra-platforms', {'value': []})
    if not isinstance(native, dict) or native.get('value') != 'x86_64-linux':
        raise PlatformError('worker is not the configured native x86_64 Linux platform')
    if (not isinstance(extras, dict) or not isinstance(extras.get('value'), list)
            or not all(isinstance(p, str) for p in extras['value'])):
        raise PlatformError('invalid worker extra-platform declarations')
    platforms = [p for p in policy['platforms'] if p == 'x86_64-linux']
    if ('aarch64-linux' in policy['platforms'] and 'aarch64-linux' in extras['value']
            and _active_arm_binfmt(binfmt_root)):
        platforms.append('aarch64-linux')
    return platforms


def health(policy, *, lock, field_marker, store_path, binfmt_root, check_lock=True):
    result = {'protocol': 1, 'workerId': policy['workerId'], 'available': False,
              'operationalMode': 'unknown', 'freeBytes': 0, 'platforms': [], 'reason': 'not ready'}
    try:
        result['operationalMode'] = 'field' if _field_mode(policy, field_marker) else 'maintenance'
        result['freeBytes'] = _free_bytes(store_path)
        admit(policy, field_marker=field_marker, store_path=store_path)
        if not policy['remoteEnabled'] or policy['workerId'] is None:
            raise PlatformError('remote worker disabled or identity not configured')
        if check_lock:
            with _session_lock(lock):
                result['platforms'] = _runtime_platforms(policy, binfmt_root)
        else:
            result['platforms'] = _runtime_platforms(policy, binfmt_root)
        if not result['platforms']:
            raise PlatformError('no validated configured platform is active at runtime')
        result.update(available=True, reason='remote session slot and runtime capability available')
    except (PlatformError, OSError) as exc:
        result['reason'] = str(exc)
    return result


def _parent_death_setup():
    if sys.platform != 'linux':
        return None  # Non-Linux host tests still exercise inherited lock lifetime.
    # This helper is single-threaded. Load libc before fork; the child performs
    # only the prctl/getppid syscalls before exec of the non-setuid Nix proxy.
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    parent = os.getpid()

    def setup():
        if prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            raise OSError(ctypes.get_errno(), 'cannot install worker parent-death cleanup')
        if os.getppid() != parent:
            os._exit(125)  # Parent exited between fork and installing prctl.
    return setup


def guard(policy, *, daemon_program, lock, field_marker, store_path, binfmt_root):
    with _session_lock(lock) as lock_fd:
        report = health(policy, lock=lock, field_marker=field_marker, store_path=store_path,
                        binfmt_root=binfmt_root, check_lock=False)
        if not report['available']:
            raise PlatformError(report['reason'])
        # Recheck after bounded runtime probes. The daemon hook checks again
        # when each derivation starts; a health snapshot is not a reservation.
        admit(policy, field_marker=field_marker, store_path=store_path)
        process = None
        stopped = [None, None]
        previous = {}

        def terminate(signum, _frame):
            if stopped[0] is None:
                stopped[:] = [signum, time.monotonic()]
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous[sig] = signal.signal(sig, terminate)
        timed_out = False
        try:
            process = subprocess.Popen([daemon_program, '--stdio', '--store', DAEMON_STORE],
                                       env={**os.environ, 'NIX_REMOTE': DAEMON_STORE,
                                            'NIX_USER_CONF_FILES': '/dev/null'}, start_new_session=True,
                                       pass_fds=(lock_fd,), preexec_fn=_parent_death_setup())
            deadline = time.monotonic() + policy['sessionTimeoutSeconds']
            if stopped[0] is not None:
                terminate(stopped[0], None)
            while process.poll() is None:
                if stopped[0] is None and time.monotonic() >= deadline:
                    timed_out = True
                    terminate(signal.SIGTERM, None)
                if stopped[0] is not None and time.monotonic() - stopped[1] >= 5:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
            if timed_out:
                raise PlatformError('remote worker session timed out')
            if stopped[0] is not None:
                return 128 + stopped[0]
            return process.returncode if process.returncode >= 0 else 128 - process.returncode
        finally:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            for sig, handler in previous.items():
                signal.signal(sig, handler)


# Deliberately fixed bounds: no peer-controlled paths, commands, limits or TTL.
RETENTION_LIMIT = 32
RETENTION_BYTES = 4096
STORE_NAME = r'/nix/store/[0123456789abcdfghijklmnpqrsvwxyz]{32}-[A-Za-z0-9+._?=-]{1,178}'


def retention_request(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    try:
        if len(raw) > RETENTION_BYTES:
            raise ValueError('oversized')
        request = json.loads(raw, object_pairs_hook=unique)
        if (not isinstance(request, dict)
                or set(request) != {'protocol', 'action', 'workerId', 'token', 'drvPath'}
                or type(request['protocol']) is not int or request['protocol'] != 1
                or request['action'] not in ('realise', 'release')
                or not isinstance(request['workerId'], str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', request['workerId'])
                or not isinstance(request['token'], str)
                or not re.fullmatch(r'[0-9a-f]{32}', request['token'])
                or not isinstance(request['drvPath'], str)
                or not re.fullmatch(STORE_NAME + r'\.drv', request['drvPath'])):
            raise ValueError('invalid fields')
        return request
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PlatformError('invalid bounded retention request') from exc


def _retained_realise(drv, root, timeout, lock_fd):
    # One output only: nix-store appends suffixes to multi-output roots. Reject
    # that graph before realization, rather than accidentally leaving a gap.
    outputs = run(['nix-store', '--store', DAEMON_STORE, '--query', '--outputs', drv],
                  timeout=10).splitlines()
    if len(outputs) != 1 or not re.fullmatch(STORE_NAME, outputs[0]) or outputs[0].endswith('.drv'):
        raise PlatformError('retention requires one statically known derivation output')
    env = {**os.environ, 'NIX_REMOTE': DAEMON_STORE, 'NIX_USER_CONF_FILES': '/dev/null'}
    # Nix registers the indirect root as part of realization, while its temporary
    # roots protect the result. Never build first and root in a second command.
    with tempfile.TemporaryFile() as stdout:
        child = subprocess.Popen(['nix-store', '--store', DAEMON_STORE, '--realise', drv,
                                  '--add-root', str(root), '--indirect'],
                                 stdin=subprocess.DEVNULL, stdout=stdout, stderr=sys.stderr,
                                 env=env, start_new_session=True, pass_fds=(lock_fd,),
                                 preexec_fn=_parent_death_setup())
        try:
            child.wait(timeout=timeout)
            if child.returncode:
                raise PlatformError('retained realization failed')
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        stdout.seek(0)
        if stdout.read(RETENTION_BYTES + 1).decode().splitlines() != [str(root)]:
            raise PlatformError('retained realization returned unexpected outputs')
    return outputs[0]


def retain(policy, raw, *, state, lock, field_marker, store_path, capacity=RETENTION_LIMIT):
    request = retention_request(raw)
    if (not policy['remoteEnabled'] or not policy['enabled'] or not policy['validated']
            or request['workerId'] != policy['workerId']):
        raise PlatformError('retention worker identity or admission mismatch')
    state = Path(state)
    with _session_lock(lock) as lock_fd:
        slots = sorted(state.iterdir())
        chosen = None
        for slot in slots:
            if slot.is_symlink() or not slot.is_dir() or not re.fullmatch(r'[0-9]+', slot.name):
                raise PlatformError('invalid retention state; operator repair required')
            # A crash before reservation can leave only atomic-write temporary
            # files. No realization starts before the metadata rename completes.
            # A crash during release can leave an empty slot. Neither has roots.
            entries = list(slot.iterdir())
            if all(not entry.is_symlink() and entry.is_file()
                   and re.fullmatch(r'\.request\.json\.[A-Za-z0-9_-]+\.tmp', entry.name)
                   for entry in entries):
                for entry in entries:
                    entry.unlink()
                slot.rmdir()
                sync_dir(state)
                continue
            if any(entry.name not in ('request.json', 'root') for entry in entries):
                raise PlatformError('unexpected retention state; operator repair required')
            metadata = slot / 'request.json'
            if metadata.is_symlink() or not metadata.is_file():
                raise PlatformError('invalid retention metadata file')
            with metadata.open('rb') as stream:
                record = retention_request(stream.read(RETENTION_BYTES + 1))
            if record['action'] != 'realise':
                raise PlatformError('invalid retention reservation action')
            if record.get('token') == request['token']:
                if any(record.get(k) != request[k] for k in ('protocol', 'workerId', 'drvPath')):
                    raise PlatformError('conflicting retention token replay')
                chosen = slot
        slots = list(state.iterdir())
        response = {**request}
        if request['action'] == 'release':
            if chosen is not None:
                (chosen / 'root').unlink(missing_ok=True)
                sync_dir(chosen)
                (chosen / 'request.json').unlink()
                sync_dir(chosen)
                chosen.rmdir()
                sync_dir(state)
            return {**response, 'released': True}
        admit(policy, field_marker=field_marker, store_path=store_path)
        if chosen is None:
            if len(slots) >= capacity:
                raise PlatformError('retention capacity exhausted; no roots evicted')
            chosen = next(state / str(i) for i in range(capacity) if not (state / str(i)).exists())
            chosen.mkdir()
            atomic_json(chosen / 'request.json', request)
            sync_dir(state)
        root = chosen / 'root'
        if root.is_symlink():
            store = os.readlink(root)
        elif root.exists():
            raise PlatformError('invalid retention root')
        else:
            store = _retained_realise(request['drvPath'], root, policy['sessionTimeoutSeconds'], lock_fd)
        if (not isinstance(store, str) or not re.fullmatch(STORE_NAME, store)
                or store.endswith('.drv') or not root.is_symlink() or os.readlink(root) != store):
            raise PlatformError('expected retained GC root was not established')
        run(['nix-store', '--store', DAEMON_STORE, '--check-validity', store], timeout=10)
        registered = run(['nix-store', '--store', DAEMON_STORE, '--query', '--roots', store], timeout=10).splitlines()
        if str(root) not in registered and f'{root} -> {store}' not in registered:
            raise PlatformError('worker retention root is not registered with Nix')
        sync_dir(chosen)
        sync_dir(state)
        return {**response, 'storePath': store, 'retained': True}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='crt-platform-worker-v1', description=__doc__)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=Path('/run/ground-station-builder/session.lock'))
    parser.add_argument('--field-marker', type=Path, default=Path('/run/ground-station/field-mode'))
    parser.add_argument('--store-path', type=Path, default=Path('/nix/store'))
    parser.add_argument('--binfmt-root', type=Path, default=Path('/proc/sys/fs/binfmt_misc'))
    parser.add_argument('--daemon-program', default='nix-daemon')
    parser.add_argument('--retention-state', type=Path, default=Path('/var/lib/ground-builder-retention'))
    parser.add_argument('mode', choices=('health', 'guard', 'admit', 'retain'))
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.policy)
        paths = {name: getattr(args, name) for name in ('field_marker', 'store_path')}
        if args.mode == 'admit':
            admit(policy, **paths)
            return 0
        if args.mode == 'retain':
            def input_timeout(_signum, _frame):
                raise PlatformError('retention input timed out')
            previous_alarm = signal.signal(signal.SIGALRM, input_timeout)
            signal.alarm(5)
            try:
                raw = sys.stdin.buffer.read(RETENTION_BYTES + 1)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous_alarm)
            print(json.dumps(retain(policy, raw, state=args.retention_state, lock=args.lock, **paths), sort_keys=True))
            return 0
        paths.update(lock=args.lock, binfmt_root=args.binfmt_root)
        if args.mode == 'health':
            print(json.dumps(health(policy, **paths), sort_keys=True))
            return 0
        return guard(policy, daemon_program=args.daemon_program, **paths)
    except (PlatformError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'platform worker: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
