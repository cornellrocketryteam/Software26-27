"""Explicit FIT-only deployment from a verified release manifest; never builds/reboots."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from .manifest import artifact_files
from .receipts import MAX_MANIFEST, decode_json, identity
from .runtime import PlatformError, atomic_json, durable_mkdir, read_json, state_lock

PARTITIONS={'tiboot3.bin':'ospi.tiboot3','tispl.bin':'ospi.tispl','u-boot.img':'ospi.u-boot','fitImage.itb':'ospi.rootfs'}
REQUIRED=set(PARTITIONS)|{'partitions','SHA256SUMS'}
FLASH_SCRIPT=Path(__file__).resolve().parents[2]/'tools/flash-ospi.sh'


def verify(manifest_path,target):
    if not re.fullmatch(r'(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',target):
        raise PlatformError('deployment target must be an explicit SSH host alias or user@host')
    path=Path(manifest_path).expanduser().resolve()
    with path.open('rb') as stream:raw=stream.read(MAX_MANIFEST+1)
    if len(raw)>MAX_MANIFEST:raise PlatformError('deployment manifest exceeds 1 MiB')
    manifest=decode_json(raw,'deployment manifest')
    if (not isinstance(manifest,dict) or type(manifest.get('schemaVersion')) is not int
            or manifest['schemaVersion']!=1 or manifest.get('host')!='fill-station'):
        raise PlatformError('deployment requires a version-1 fill-station release manifest')
    release=identity(manifest.get('releaseId'),'release ID')
    vehicle=identity(manifest.get('vehicle'),'vehicle profile')
    artifact=manifest.get('artifacts',{})
    artifact=artifact.get('ospi') if isinstance(artifact,dict) else None
    if not isinstance(artifact,dict) or not isinstance(artifact.get('storePath'),str):
        raise PlatformError('deployment requires the complete ospi artifact, not fit/sd/system alone')
    root=Path(artifact['storePath'])
    if not root.is_absolute() or not root.is_dir():raise PlatformError('OSPI output must be an existing absolute directory')
    files=artifact_files(root)
    if files!=artifact.get('files'):raise PlatformError('OSPI bytes/inventory disagree with release manifest')
    if ({f['relativePath'] for f in files}!=REQUIRED or any(f['kind']!='file' for f in files)):
        raise PlatformError('OSPI output must contain exactly the six regular bundle files')
    by_name={f['relativePath']:f for f in files}
    if any(by_name[name]['sizeBytes']<=0 for name in PARTITIONS):raise PlatformError('OSPI binary payloads must not be empty')
    parsed={}
    for line in (root/'SHA256SUMS').read_text().splitlines():
        match=re.fullmatch(r'([0-9a-f]{64}) [ *]([A-Za-z0-9._-]+)',line)
        if not match or match[2] in parsed:raise PlatformError('invalid or duplicate OSPI checksum entry')
        parsed[match[2]]=match[1]
    if set(parsed)!=set(PARTITIONS) or any(by_name[name]['sha256']!=digest for name,digest in parsed.items()):
        raise PlatformError('OSPI SHA256SUMS disagrees with verified payload')
    mapping={}
    for line in (root/'partitions').read_text().splitlines():
        parts=line.split()
        if len(parts)!=2 or parts[0] in mapping:raise PlatformError('invalid or duplicate partition entry')
        mapping[parts[0]]=parts[1]
    if mapping!=PARTITIONS:raise PlatformError('OSPI partition mapping is not the reviewed layout')
    return root,files,{'releaseId':release,'vehicle':vehicle,'manifest':str(path),
        'manifestSha256':hashlib.sha256(raw).hexdigest(),'target':target,'mode':'fit',
        'fitSha256':by_name['fitImage.itb']['sha256'],'fitBytes':by_name['fitImage.itb']['sizeBytes'],
        'bootloadersWritten':False,'rebootRequested':False,'runtimeAcceptance':'pending'}


def _payload_inventory(files):
    return [{k:f[k] for k in ('relativePath','kind','sizeBytes','sha256')} for f in files]


def execute(state,args):
    root,files,plan=verify(args.manifest,args.target)
    if args.dry_run:return {**plan,'dryRun':True,'state':'verified-plan','note':'No SSH, flash, build, reboot or state writes performed'}
    if not FLASH_SCRIPT.is_file():raise PlatformError('packaged flash script is unavailable')
    durable_mkdir(state)
    with state_lock(state,name='board-deployment'):
        attempt=uuid.uuid4().hex
        record_path=state/'deployments'/plan['releaseId']/(attempt+'.json')
        log_path=record_path.with_suffix('.log')
        durable_mkdir(record_path.parent)
        record={**plan,'version':1,'attemptId':attempt,'record':str(record_path),'log':str(log_path),
                'createdAt':datetime.now(timezone.utc).isoformat(),'state':'prepared','outcome':'not-started'}
        atomic_json(record_path,record)
        with tempfile.TemporaryDirectory(prefix='crt-deploy-') as directory:
            stage=Path(directory)
            for name in sorted(REQUIRED):shutil.copyfile(root/name,stage/name)
            if _payload_inventory(artifact_files(stage))!=_payload_inventory(files):
                record.update(state='failed',outcome='not-started');atomic_json(record_path,record)
                raise PlatformError('staged OSPI bytes changed; no flash attempted')
            record.update(state='flashing',outcome='unconfirmed');atomic_json(record_path,record)
            print('Deployment log: '+str(log_path),file=sys.stderr)
            try:
                with log_path.open('wb') as log:
                    # No automatic kill/deadline while flash erase/write may be active.
                    # SSH handshake is bounded by the script; an operator interrupt
                    # still leaves an explicitly unconfirmed physical outcome.
                    process=subprocess.run(['bash',str(FLASH_SCRIPT),args.target,'fit',str(stage)],
                        stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,check=False)
            except (OSError,KeyboardInterrupt):
                record.update(state='failed',outcome='unconfirmed');atomic_json(record_path,record)
                raise
            if process.returncode:
                record.update(state='failed',outcome='unconfirmed',exitCode=process.returncode)
                atomic_json(record_path,record)
                with log_path.open('rb') as stream:
                    stream.seek(max(0,log_path.stat().st_size-4096));diagnostic=stream.read().decode(errors='replace')
                raise PlatformError('deployment failed; physical completion unconfirmed; see '+str(log_path)+'\n'+diagnostic)
        record.update(state='flash-verified',outcome='verified',completedAt=datetime.now(timezone.utc).isoformat())
        atomic_json(record_path,record)
        return record


def status(state):
    records=[]
    for path in sorted((state/'deployments').glob('*/*.json')):
        record=read_json(path)
        if not isinstance(record,dict) or type(record.get('version')) is not int or record.get('version')!=1:
            raise PlatformError('invalid deployment record: '+str(path))
        records.append(record)
    return records
