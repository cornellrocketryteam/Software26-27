"""Frozen tracked working source and streamed artifact SHA256 inventories."""
import hashlib
import os
from pathlib import Path
import shutil
import stat
from .runtime import PlatformError, run, sync_dir


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(repo, destination):
    def git(*args):
        return run(['git', '-C', repo, *args])
    commit = git('rev-parse', 'HEAD').strip()
    object_format = git('rev-parse', '--show-object-format').strip()
    head_inventory = {}
    for entry in git('ls-tree', '-r', '-z', '--full-tree', commit).split('\0'):
        if entry:
            metadata, name = entry.split('\t', 1)
            mode, _, object_id = metadata.split()
            head_inventory[name] = (mode, object_id)
    staged = git('ls-files', '--stage', '-z')
    if any(entry.startswith('160000 ') for entry in staged.split('\0')):
        raise PlatformError('source snapshot does not yet support Git submodules')
    tracked = [p for p in git('ls-files', '-z', '--cached').split('\0') if p]
    untracked = [p for p in git('ls-files', '-z', '--others', '--exclude-standard').split('\0')
                 if p and not p.startswith('outputs/platform/')]
    destination.mkdir(parents=True)
    captured_names = []
    for name in sorted(set(tracked)):
        source = repo / name
        if not source.exists() and not source.is_symlink():
            continue  # tracked deletion in working tree
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            link = os.readlink(source)
            target.symlink_to(link)
        elif source.is_file():
            shutil.copy2(source, target)
            with target.open('rb') as stream:
                os.fsync(stream.fileno())
        else:
            raise PlatformError(f'unsupported tracked source: {name}')
        captured_names.append(name)
    # Inspect the captured files, not the mutable source or Git's stat/index cache.
    # Git records file type and executable mode; the snapshot digest retains full modes.
    inventory = []
    captured_inventory = {}
    for name in captured_names:
        target = destination / name
        mode = stat.S_IMODE(target.lstat().st_mode)
        if target.is_symlink():
            link = os.readlink(target)
            content = os.fsencode(link)
            blob = hashlib.new(object_format, b'blob ' + str(len(content)).encode() + b'\0' + content)
            captured_inventory[name] = ('120000', blob.hexdigest())
            inventory.append([name, mode, 'symlink', link])
        elif target.is_file():
            blob = hashlib.new(object_format, b'blob ' + str(target.stat().st_size).encode() + b'\0')
            content_sha256 = hashlib.sha256()
            with target.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    blob.update(chunk)
                    content_sha256.update(chunk)
            captured_inventory[name] = ('100755' if mode & stat.S_IXUSR else '100644', blob.hexdigest())
            inventory.append([name, mode, 'file', content_sha256.hexdigest()])
        else:
            raise PlatformError(f'unsupported captured source: {name}')
    dirty = captured_inventory != head_inventory or bool(untracked)
    # Include filenames/types/modes as well as bytes in the stable source identity.
    import json
    digest = hashlib.sha256(json.dumps(inventory, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
    for parent, _, _ in os.walk(destination, topdown=False):
        sync_dir(parent)
    lock = destination / 'flake.lock'
    if not lock.is_file():
        raise PlatformError('flake.lock missing from source snapshot; refusing an unlocked build')
    if git('rev-parse', 'HEAD').strip() != commit:
        raise PlatformError('HEAD changed while capturing source snapshot; retry the build')
    return {'commit': commit, 'dirty': dirty, 'snapshot': str(destination), 'snapshotSha256': digest,
            'lockSha256': sha256(lock), 'excludedUntracked': untracked,
            'snapshotPolicy': 'tracked-working-files-v1'}


def artifact_files(store):
    store = Path(store)
    files = []
    paths = [store] if store.is_file() else sorted(store.rglob('*'))
    for path in paths:
        if path.is_symlink():
            content = os.readlink(path).encode()
            files.append({'path': str(path), 'relativePath': str(path.relative_to(store)), 'kind': 'symlink',
                          'sizeBytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
        elif path.is_file():
            files.append({'path': str(path), 'relativePath': str(path.relative_to(store)) if path != store else path.name,
                          'kind': 'file', 'sizeBytes': path.stat().st_size, 'sha256': sha256(path)})
    if not files:
        raise PlatformError(f'build output is empty or absent: {store}')
    return files
