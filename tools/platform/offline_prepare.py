"""Explicit cache-only preparation; never realize, build, or change global trust."""
import time
from pathlib import Path
from urllib.parse import urlsplit
from . import client_cache, offline_audit, offline_pins
from .runtime import PlatformError

run=offline_audit.bounded_run


def execute(state,drv,url,public_key,*,dry_run=False,pin=False,timeout_seconds=600):
    # Reuse existing credential-free HTTP(S) URL / Ed25519 key validation only;
    # rendering this block does not install or modify any Nix configuration.
    client_cache.block({'url':url,'publicKey':public_key})
    parsed=urlsplit(url)
    url=parsed._replace(path=parsed.path.rstrip('/')+'/',query='',fragment='').geturl()
    if type(timeout_seconds) is not int or not 1<=timeout_seconds<=3600:raise PlatformError('Copy time budget must be 1..3600 seconds')
    report=offline_audit.execute(drv)
    inventory=report['inventory']
    if report['unverifiedPaths'] or inventory['unresolvedOutputs'] or report['assessment'] not in ('missing_static_inputs','static_inputs_present'):
        raise PlatformError('Preparation requires a fully understood/verified static graph; inspect offline-audit')
    paths=sorted(set(report['missingPaths']))
    if len(paths)>4096:raise PlatformError('Too many missing paths for bounded cache preparation')
    for path in paths:
        if offline_audit.store_path(path)!=path or path.endswith('.drv'):
            raise PlatformError('Restore missing derivation metadata before cache-only preparation')
    result={'schemaVersion':1,'derivation':drv,'cacheUrl':url,'cachePublicKey':public_key,
            'dryRun':dry_run,'plannedPaths':paths,'copied':False,'copyAttempted':False,'copyFailed':False,
            'prepared':False,'offlineBuildValidated':False,'pin':None,
            'scope':'cache-only static inputs; no raw URL fetch, compilation, activation or global trust change'}
    if dry_run:return result
    deadline=time.monotonic()+timeout_seconds
    for start in range(0,len(paths),32):
        remaining=deadline-time.monotonic()
        if remaining<=0:
            result.update(copyFailed=True,copyFailure='copy_budget_exhausted');break
        try:
            result['copyAttempted']=True
            run(['nix','--extra-experimental-features','nix-command','copy','--from',url,'--to','daemon',
                 '--option','require-sigs','true','--option','trusted-public-keys',public_key,
                 '--option','extra-trusted-public-keys','','--option','substituters','',
                 '--option','builders','','--option','max-jobs','0','--option','substitute','false',
                 '--option','connect-timeout','3','--option','stalled-download-timeout','15',
                 *paths[start:start+32]],timeout=min(remaining,300))
            result['copied']=True
        except PlatformError:
            result.update(copyFailed=True,copyFailure='copy_did_not_complete');break
    final=offline_audit.execute(drv)
    result.update(remainingMissingPaths=final['missingPaths'],unverifiedPaths=final['unverifiedPaths'],
                  unresolvedOutputs=final['inventory']['unresolvedOutputs'],assessment=final['assessment'])
    result['newlyVerifiedPlannedPaths']=sorted(set(paths)-set(final['missingPaths'])-set(final['unverifiedPaths']))
    result['prepared']=not result['copyFailed'] and final['assessment']=='static_inputs_present'
    if result['prepared'] and pin:
        result['pin']=offline_pins.execute(Path(state),drv)
    return result
