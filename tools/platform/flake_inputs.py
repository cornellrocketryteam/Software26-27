"""Inspect/pin existing locked GitHub source trees without fetching a flake."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from . import offline_audit, offline_pins
from .runtime import PlatformError, atomic_json

run=offline_audit.bounded_run


def validate_references(nodes,root):
    label=re.compile(r'[A-Za-z0-9._-]{1,64}\Z')
    for name,node in nodes.items():
        if not isinstance(name,str) or not label.fullmatch(name) or not isinstance(node,dict):
            raise PlatformError('Invalid locked input node')
        edges=node.get('inputs',{})
        if not isinstance(edges,dict) or len(edges)>64:raise PlatformError('Invalid or oversized locked input references')
        for key,value in edges.items():
            if not isinstance(key,str) or not label.fullmatch(key):raise PlatformError('Invalid locked input name')
            if isinstance(value,str):
                if value not in nodes:raise PlatformError('Missing locked input reference')
            elif isinstance(value,list):
                if len(value)>64 or any(not isinstance(part,str) or not label.fullmatch(part) for part in value):
                    raise PlatformError('Invalid follows reference')
            else:raise PlatformError('Unsupported locked input reference')
    resolved={}
    def edge(node,key,seen):
        pair=(node,key)
        if pair in seen or len(seen)>=128:raise PlatformError('Cyclic or oversized follows reference')
        if pair in resolved:return resolved[pair]
        if key not in nodes[node].get('inputs',{}):raise PlatformError('Missing follows path')
        value=nodes[node]['inputs'][key]
        if isinstance(value,str):target=value
        else:
            target=root
            for part in value:target=edge(target,part,seen|{pair})
        resolved[pair]=target
        return target
    for name,node in nodes.items():
        for key in node.get('inputs',{}):edge(name,key,set())


def read_lock(path):
    try:fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    except OSError as error:raise PlatformError('Cannot open regular flake.lock') from error
    try:
        details=os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_size>1024*1024:raise PlatformError('flake.lock must be a bounded regular file')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(1024*1024+1)
        if len(raw)>1024*1024:raise PlatformError('flake.lock exceeds limit')
        return raw
    finally:os.close(fd)


def execute(lock_file,state,*,pin=False,dry_run=False):
    lock_file=Path(lock_file).absolute();raw=read_lock(lock_file)
    try:data=json.loads(raw)
    except (ValueError,UnicodeError) as error:raise PlatformError('Invalid flake.lock JSON') from error
    if not isinstance(data,dict) or data.get('version')!=7 or not isinstance(data.get('nodes'),dict):raise PlatformError('Unsupported flake.lock schema')
    nodes=data['nodes'];root=data.get('root')
    if not isinstance(root,str) or root not in nodes or not 1<=len(nodes)<=65:raise PlatformError('Invalid or oversized locked input graph')
    validate_references(nodes,root)
    deadline=time.monotonic()+120
    def budget():
        remaining=deadline-time.monotonic()
        if remaining<=0:raise PlatformError('Locked source inspection budget exhausted')
        return remaining
    records=[];unsupported=[]
    for name,node in nodes.items():
        if name==root:continue
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}',name) or not isinstance(node,dict):raise PlatformError('Invalid locked input record')
        locked=node.get('locked')
        if not isinstance(locked,dict) or locked.get('type')!='github' or locked.get('name','source')!='source':
            unsupported.append(name);continue
        if not isinstance(locked.get('rev'),str) or not re.fullmatch(r'[0-9a-fA-F]{40}',locked['rev']):
            unsupported.append(name);continue
        value=locked.get('narHash')
        if not isinstance(value,str) or not value.startswith('sha256-'):raise PlatformError('Expected SHA256 narHash for locked GitHub source')
        try:
            if len(base64.b64decode(value[7:],validate=True))!=32:raise ValueError()
        except ValueError:raise PlatformError('Invalid locked source narHash') from None
        source=run(['nix-store','--store','daemon','--print-fixed-path','--recursive','sha256',value,'source'],timeout=min(10,budget())).strip()
        if not offline_audit.STORE.fullmatch(source) or not source.endswith('-source'):raise PlatformError('Unexpected locked source store path')
        records.append({'node':name,'storePath':source})
    paths=sorted({row['storePath'] for row in records})
    missing=[];existing=[]
    for path in paths:
        budget()
        (existing if os.path.lexists(path) else missing).append(path)
    unverified=[]
    if existing:
        try:run(['nix-store','--store','daemon','--check-validity',*existing],timeout=min(30,budget()))
        except PlatformError:unverified=existing
    assessment=('unsupported_inputs' if unsupported else 'unverifiable' if unverified else
                'missing_locked_sources' if missing else 'locked_sources_present')
    digest=hashlib.sha256(raw).hexdigest()
    result={'schemaVersion':1,'lockSha256':digest,'inputs':records,'sourcePathCount':len(paths),
            'missingPaths':missing,'unverifiedPaths':unverified,'unsupportedInputs':unsupported,
            'assessment':assessment,'retained':False,'pin':None,'dryRun':dry_run,
            'offlineEvaluationValidated':False,'offlineBuildValidated':False,
            'scope':'existing locked GitHub source trees only; no fetch, archive or target compilation'}
    if read_lock(lock_file)!=raw:raise PlatformError('flake.lock changed during inspection; retry the exact source revision')
    if pin and not dry_run and assessment=='locked_sources_present':
        literals=' '.join(json.dumps(value) for value in paths)
        expression=('builtins.derivation { name="crt-flake-evaluation-inputs"; '
          'system="crt-retention-metadata-only"; builder="/__crt_metadata_only_never_build__"; '
          'lockDigest="'+digest+'"; retainedInputs=map builtins.storePath [ '+literals+' ]; }')
        drv=run(['nix-instantiate','--store','daemon','--option','substituters','',
                 '--option','builders','','--option','allow-import-from-derivation','false',
                 '--expr',expression],timeout=min(30,budget())).strip()
        if not offline_audit.STORE.fullmatch(drv) or not drv.endswith('.drv'):raise PlatformError('Unexpected flake source metadata derivation')
        receipt=offline_pins.execute(Path(state),drv)
        result.update(retained=True,pin=receipt)
        descriptor={key:result[key] for key in ('lockSha256','inputs','sourcePathCount','scope')}
        atomic_json(Path(receipt['root']).parent/'flake-inputs.json',descriptor)
    return result
