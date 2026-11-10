"""Bounded subprocesses and durable, process-safe state primitives."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


class PlatformError(Exception):
    pass


def run(argv, *, cwd=None, timeout=10, env=None, log=None):
    """No shell; disk-backed output; kill the process group on timeout."""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen([str(a) for a in argv], cwd=cwd, env=env,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
        except OSError as exc:
            raise PlatformError(f'{argv[0]} unavailable: {exc}') from exc
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        if log:
            stderr.seek(0)
            with Path(log).open('wb') as dest:
                import shutil
                shutil.copyfileobj(stderr, dest)
        stderr.seek(0, os.SEEK_END)
        length = stderr.tell()
        stderr.seek(max(0, length - 65536))
        diagnostic = stderr.read().decode('utf-8', errors='replace')
        if timed_out:
            raise PlatformError(f'{argv[0]} timed out after {timeout}s: {diagnostic}')
        if process.returncode:
            raise PlatformError(f'{argv[0]} exited {process.returncode}: {diagnostic}')
        stdout.seek(0)
        data = stdout.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise PlatformError(f'{argv[0]} response exceeds 16 MiB')
        return data.decode('utf-8', errors='surrogateescape')


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (ValueError, OSError) as exc:
        raise PlatformError(f'cannot read JSON {path}: {exc}') from exc


def json_response(text, label):
    try:
        return json.loads(text)
    except ValueError as exc:
        raise PlatformError(f'{label}: invalid JSON response') from exc


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextmanager
def state_lock(state, name='outbox', timeout=10):
    state.mkdir(parents=True, exist_ok=True)
    with (state / f'{name}.lock').open('a') as stream:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise PlatformError(f'{name} busy; retry after current operation completes')
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
