"""Explicit local GC roots for audited static inputs; no realization or fetch."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
from . import offline_audit
from .runtime import PlatformError, atomic_bytes, atomic_json, state_lock, sync_dir

run=offline_audit.bounded_run
PIN_ID=re.compile(r'[0-9a-f]{32}\Z')


def execute(state,drv,*,dry_run=False):
    audit=offline_audit.execute(drv)
    if audit['assessment']!='static_inputs_present':
        raise PlatformError('Input pin requires a fresh passing static audit; inspect offline-audit first')
    inventory=audit['inventory']
    paths=sorted(set(inventory['sources']+inventory['derivations']+inventory['fixedOutputs']))
    if not paths or inventory['unresolvedOutputs']:raise PlatformError('Incomplete static pin inventory')
    paths=[offline_audit.store_path(value) for value in paths]
    if dry_run:return {'dryRun':True,'retained':False,'pathCount':len(paths),'offlineBuildValidated':False}
    state=Path(state).resolve();base=state/'offline-input-pins'
    with state_lock(state/'.offline-input-pins.lock'):
        if base.is_symlink():raise PlatformError('Input pin directory must not be a symlink')
        base.mkdir(mode=0o700,parents=True,exist_ok=True)
        if base.stat().st_mode&0o022:raise PlatformError('Input pin directory must not be writable by others')
        if len(list(base.iterdir()))>=8:raise PlatformError('Input pin capacity reached; no pins evicted')
        pin_id=uuid.uuid4().hex;directory=base/pin_id;directory.mkdir(mode=0o700)
        root=directory/'root'
        atomic_json(directory/'audit.json',audit)
        # Values have been restricted to Nix store-path characters (no ${...}).
        # Space-separated Nix list syntax, not a comma-separated JSON array.
        literals=' '.join(json.dumps(value) for value in paths)
        expression=('builtins.derivation { name="crt-offline-input-pin"; '
                    'system="crt-retention-metadata-only"; '
                    'builder="/__crt_metadata_only_never_build__"; '
                    'retainedInputs=map builtins.storePath [ '+literals+' ]; }\n')
        atomic_bytes(directory/'pin.nix',expression.encode())
        # Instantiation registers the derivation root while its temporary roots
        # protect inputs. Never --realise this metadata-only object.
        run(['nix-instantiate','--store','daemon','--option','substituters','',
             '--option','builders','','--option','allow-import-from-derivation','false',
             '--add-root',str(root),'--indirect',str(directory/'pin.nix')],timeout=120)
        if not root.is_symlink():raise PlatformError('Metadata GC root was not created; partial pin retained for inspection')
        metadata=str(root.readlink())
        if not offline_audit.STORE.fullmatch(metadata) or not metadata.endswith('.drv'):
            raise PlatformError('Unexpected metadata root target; partial pin retained')
        references=set(run(['nix-store','--store','daemon','--query','--requisites',metadata],timeout=30).splitlines())
        roots=run(['nix-store','--store','daemon','--query','--roots',metadata],timeout=30).splitlines()
        if not set(paths)<=references or not any(line.split(' -> ',1)[0]==str(root) for line in roots):
            raise PlatformError('Metadata references/root registration incomplete; partial pin retained')
        receipt={'schemaVersion':1,'pinId':pin_id,'derivation':drv,'metadataDerivation':metadata,
                 'root':str(root),'retainedPathCount':len(paths),
                 'inventorySha256':hashlib.sha256(json.dumps(paths,separators=(',',':')).encode()).hexdigest(),
                 'createdAt':datetime.now(timezone.utc).isoformat(),'retained':True,
                 'offlineBuildValidated':False,'scope':'local static inputs only; no fetch, realization or worker admission'}
        atomic_json(directory/'receipt.json',receipt)
        return receipt


def receipt_at(path):
    """Bounded nonblocking descriptor read; reject links and special files."""
    try:fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    except FileNotFoundError:return None
    except OSError as error:raise PlatformError('Cannot open managed input pin receipt') from error
    try:
        details=os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_size>16384:
            raise PlatformError('Input pin receipt must be a bounded regular file')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(16385)
        if len(raw)>16384:raise PlatformError('Input pin receipt exceeds limit')
        try:return json.loads(raw)
        except (ValueError,UnicodeError) as error:raise PlatformError('Invalid input pin receipt JSON') from error
    finally:os.close(fd)


def release(state,pin_id,*,dry_run=False):
    if not isinstance(pin_id,str) or not PIN_ID.fullmatch(pin_id):raise PlatformError('Expected exact managed pin ID')
    state=Path(state).resolve();base=state/'offline-input-pins';directory=base/pin_id
    def inspect():
        if base.is_symlink() or directory.is_symlink() or not directory.is_dir():raise PlatformError('Invalid managed pin directory')
        receipt=receipt_at(directory/'receipt.json')
        if receipt is not None and (not isinstance(receipt,dict) or receipt.get('pinId')!=pin_id):raise PlatformError('Invalid managed pin receipt')
        root=directory/'root'
        if os.path.lexists(root) and not root.is_symlink():raise PlatformError('Managed root is not a symlink')
        if root.is_symlink():
            target=str(root.readlink())
            if not offline_audit.STORE.fullmatch(target) or not target.endswith('-crt-offline-input-pin.drv'):
                raise PlatformError('Unexpected managed root target; inspect manually')
            if receipt is not None and receipt.get('metadataDerivation')!=target:raise PlatformError('Managed root differs from receipt')
        return root
    root=inspect()
    if dry_run:return {'pinId':pin_id,'dryRun':True,'released':False,'wouldRemoveRoot':root.is_symlink()}
    with state_lock(state/'.offline-input-pins.lock'):
        root=inspect()
        history=state/'offline-input-pin-history';destination=history/pin_id
        if history.is_symlink():raise PlatformError('Input pin history must not be a symlink')
        history.mkdir(mode=0o700,exist_ok=True)
        if history.stat().st_mode&0o022 or os.path.lexists(destination):raise PlatformError('Unsafe or conflicting pin archive')
        removed=root.is_symlink()
        if removed:root.unlink();sync_dir(directory)
        result={'pinId':pin_id,'released':True,'rootRemoved':removed,'storeDataDeleted':False,
                'garbageCollectionRun':False,'archiveDirectory':str(destination)}
        atomic_json(directory/'released.json',result)
        directory.rename(destination);sync_dir(base);sync_dir(history)
        return result


def status(state):
    """Local receipt/link inspection only; not a fresh daemon registration check."""
    base=Path(state).resolve()/'offline-input-pins'
    if base.is_symlink():raise PlatformError('Invalid input pin state directory')
    if not base.exists():return []
    if not base.is_dir():raise PlatformError('Invalid input pin state directory')
    result=[]
    for directory in sorted(base.iterdir()):
        if directory.is_symlink() or not directory.is_dir() or not PIN_ID.fullmatch(directory.name):
            result.append({'pinId':directory.name,'state':'invalid'});continue
        receipt_path=directory/'receipt.json';root=directory/'root'
        receipt=receipt_at(receipt_path)
        if receipt is None:
            result.append({'pinId':directory.name,'state':'partial','rootPresent':root.is_symlink()});continue
        if not isinstance(receipt,dict) or receipt.get('pinId')!=directory.name:raise PlatformError('Invalid input pin receipt')
        matches=root.is_symlink() and str(root.readlink())==receipt.get('metadataDerivation')
        result.append({'pinId':directory.name,'state':'recorded' if matches else 'root_missing_or_changed',
                       'derivation':receipt.get('derivation'),'retainedPathCount':receipt.get('retainedPathCount'),
                       'daemonRegistrationRechecked':False})
    return result
