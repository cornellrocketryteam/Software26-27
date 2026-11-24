"""Conservative local static-input audit, never an offline build certificate."""
import os
import re
import time
import selectors
import signal
import subprocess
from .runtime import PlatformError, json_response

STORE=re.compile(r'/nix/store/[0-9a-z]{32}-[A-Za-z0-9+._?=-]+\Z')


def bounded_run(argv,*,timeout,output_limit=16*1024*1024):
    """No shell or disk spool; terminate the child group at byte/time limits."""
    try:
        process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,start_new_session=True)
    except OSError as error:raise PlatformError(f'{argv[0]} unavailable: {error}') from error
    deadline=time.monotonic()+timeout
    buffers={'stdout':bytearray(),'stderr':bytearray()}
    settled=False
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ,'stdout')
            selector.register(process.stderr,selectors.EVENT_READ,'stderr')
            while selector.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0:raise PlatformError('Audit subprocess time budget exhausted')
                for key,_ in selector.select(min(remaining,0.1)):
                    limit=output_limit if key.data=='stdout' else 65536
                    chunk=os.read(key.fd,min(65536,limit-len(buffers[key.data])+1))
                    if not chunk:selector.unregister(key.fileobj);continue
                    buffers[key.data].extend(chunk)
                    if len(buffers[key.data])>limit:raise PlatformError('Audit subprocess output limit exceeded')
            try:code=process.wait(timeout=max(0.001,deadline-time.monotonic()))
            except subprocess.TimeoutExpired:raise PlatformError('Audit subprocess time budget exhausted') from None
        settled=True
        if code:raise PlatformError(f'{argv[0]} exited {code}: '+buffers['stderr'].decode('utf-8',errors='replace'))
        return buffers['stdout'].decode('utf-8',errors='surrogateescape')
    finally:
        # Kill the whole group even if the parent exited but left pipe-owning children.
        if not settled:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        process.wait()
        process.stdout.close();process.stderr.close()

run=bounded_run


def check_time(deadline):
    if deadline is not None and time.monotonic()>=deadline:
        raise PlatformError('Audit time budget exhausted during metadata/filesystem inspection')


def store_path(value):
    if not isinstance(value,str):raise PlatformError('Invalid store path in derivation metadata')
    value=value if value.startswith('/nix/store/') else '/nix/store/'+value
    if not STORE.fullmatch(value):raise PlatformError('Unsupported store path in derivation metadata')
    return value


def inputs(payload,root,deadline=None):
    if not isinstance(payload,dict):raise PlatformError('Unsupported derivation JSON')
    modern='version' in payload
    if modern:
        if payload.get('version')!=4 or not isinstance(payload.get('derivations'),dict):raise PlatformError('Unsupported derivation JSON version')
        payload=payload['derivations']
    if len(payload)>10000:raise PlatformError('Oversized derivation graph')
    graph={}
    for key,value in payload.items():
        check_time(deadline)
        graph[store_path(key)]=value
    if root not in graph or len(graph)>10000:raise PlatformError('Missing root or oversized derivation graph')
    if any(not isinstance(v,dict) or not isinstance(v.get('outputs'),dict) or not v['outputs'] for v in graph.values()):raise PlatformError('Unsupported derivation record')
    sources=set();fixed=set();unresolved=[]
    for name,entry in graph.items():
        check_time(deadline)
        record_modern=modern or entry.get("version")==4
        if "version" in entry and entry["version"]!=4:raise PlatformError("Unsupported derivation record version")
        if not isinstance(entry,dict) or not isinstance(entry.get('outputs'),dict) or not entry['outputs']:
            raise PlatformError('Unsupported derivation output metadata')
        if record_modern:
            data=entry.get('inputs',{})
            if not isinstance(data,dict):raise PlatformError('Unsupported derivation input metadata')
            srcs=data.get('srcs');drvs=data.get('drvs')
        else:srcs=entry.get('inputSrcs');drvs=entry.get('inputDrvs')
        if not isinstance(srcs,list) or not isinstance(drvs,dict):raise PlatformError('Unsupported derivation input metadata')
        sources.update(store_path(p) for p in srcs)
        for drv,required in drvs.items():
            dependency=store_path(drv)
            if dependency not in graph:raise PlatformError('Incomplete recursive derivation graph')
            if record_modern and not isinstance(required,list):
                if not isinstance(required,dict) or not isinstance(required.get('outputs'),list) or not isinstance(required.get('dynamicOutputs',{}),dict):
                    raise PlatformError('Unsupported dependency metadata')
                if required.get('dynamicOutputs'):unresolved.append(name+':dynamic-input')
                required=required['outputs']
            if not isinstance(required,list) or any(not isinstance(v,str) for v in required):raise PlatformError('Unsupported dependency outputs')
            if any(v not in graph[dependency].get('outputs',{}) for v in required):raise PlatformError('Missing dependency output metadata')
        for output,metadata in entry['outputs'].items():
            if not isinstance(metadata,dict):raise PlatformError('Unsupported output metadata')
            path=metadata.get('path')
            is_fixed=bool(metadata.get('hash'))
            if not path and is_fixed:
                environment=entry.get('env',{})
                path=environment.get(output) if isinstance(environment,dict) else None
            if not path:unresolved.append(name+':'+output)
            elif is_fixed:fixed.add(store_path(path))
            else:store_path(path) # Validate without requiring unbuilt ordinary outputs.
    if len(sources)+len(graph)+len(fixed)>20000:raise PlatformError('Static-input path inventory exceeds limit')
    return {'sources':sorted(sources),'derivations':sorted(graph),'fixedOutputs':sorted(fixed),'unresolvedOutputs':sorted(set(unresolved))}


def execute(drv,timeout_seconds=120):
    if not isinstance(drv,str) or not STORE.fullmatch(drv) or not drv.endswith('.drv'):raise PlatformError('Expected absolute /nix/store/*.drv path')
    if type(timeout_seconds) is not int or not 1<=timeout_seconds<=300:raise PlatformError('Audit timeout must be 1..300 seconds')
    deadline=time.monotonic()+timeout_seconds
    raw=run(['nix','--extra-experimental-features','nix-command','derivation','show','--recursive',
             '--offline','--store','daemon','--option','substituters','','--option','builders','',drv],timeout=timeout_seconds)
    check_time(deadline)
    inventory=inputs(json_response(raw,'derivation graph'),drv,deadline)
    paths=sorted(set(inventory['sources']+inventory['derivations']+inventory['fixedOutputs']))
    missing=[]
    for path in paths:
        check_time(deadline)
        absent=not os.path.lexists(path)
        check_time(deadline)
        if absent:missing.append(path)
    missing_set=set(missing)
    existing=[p for p in paths if p not in missing_set]
    verified=[];unverified=[]
    for start in range(0,len(existing),128):
        batch=existing[start:start+128]
        remaining=deadline-time.monotonic()
        if remaining<=0:
            unverified.extend(existing[start:]);break
        try:
            run(['nix-store','--store','daemon','--check-validity',*batch],timeout=min(20,remaining))
            verified.extend(batch)
        except PlatformError:unverified.extend(batch)
    assessment=('unverifiable' if unverified or inventory['unresolvedOutputs'] else
                'missing_static_inputs' if missing else 'static_inputs_present')
    return {'schemaVersion':1,'derivation':drv,'store':'local-daemon','assessment':assessment,
            'missingPaths':missing,'unverifiedPaths':unverified,'verifiedPathCount':len(verified),
            'inventory':inventory,'offlineBuildValidated':False,'gcRootsCreated':False,
            'scope':'conservative full static graph; no realization, fetch, retention or network-isolated build proof'}
