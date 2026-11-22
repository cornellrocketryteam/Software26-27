"""Add/remove an optional signed cache in Determinate's custom config only."""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import hashlib
from urllib.parse import urlsplit

from .runtime import PlatformError, sync_dir

BEGIN = '# BEGIN CRT OPTIONAL CACHE (managed)'
END = '# END CRT OPTIONAL CACHE (managed)'
TARGET = Path('/etc/nix/nix.custom.conf')
ROOT_UID = 0


def block(settings):
    url=settings['url'];key=settings['publicKey']
    if not isinstance(url,str) or any(c.isspace() or ord(c)<32 for c in url):
        raise PlatformError('cache URL must not contain whitespace or control characters')
    parsed=urlsplit(url)
    if (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or '#' in url):
        raise PlatformError('cache URL must be HTTP(S), without credentials, query or fragment')
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9._-]+:[A-Za-z0-9+/]+={0,2}',key):
        raise PlatformError('invalid cache public key')
    try:
        if len(base64.b64decode(key.split(':',1)[1],validate=True))!=32:raise ValueError()
    except ValueError:raise PlatformError('cache public key must encode 32 bytes') from None
    connect=settings.get('connectTimeoutSeconds',3);stalled=settings.get('stalledTimeoutSeconds',15)
    if type(connect) is not int or not 1<=connect<=10 or type(stalled) is not int or not 1<=stalled<=60:
        raise PlatformError('cache timeouts must be bounded integers')
    return '\n'.join([BEGIN,
        '# Adds to existing caches/keys; no build worker or upload account is enabled.',
        'extra-substituters = '+url.rstrip('/')+'/?priority=20&retry-attempts=1',
        'extra-trusted-public-keys = '+key,
        '# Nix exposes these HTTP timeouts globally, not per cache.',
        'connect-timeout = '+str(connect),'stalled-download-timeout = '+str(stalled),
        'require-sigs = true','fallback = true',END,''])


def boundaries(text):
    lines=text.splitlines(keepends=True)
    starts=[i for i,x in enumerate(lines) if x.rstrip('\r\n')==BEGIN]
    ends=[i for i,x in enumerate(lines) if x.rstrip('\r\n')==END]
    if not starts and not ends:return lines,None
    if len(starts)!=1 or len(ends)!=1 or starts[0]>=ends[0]:
        raise PlatformError('custom Nix config has incomplete or duplicate managed cache blocks')
    return lines,(starts[0],ends[0]+1)


def remove(text):
    lines,span=boundaries(text)
    return text if span is None else ''.join(lines[:span[0]]+lines[span[1]:])


def update(text,settings):
    rendered=block(settings)
    lines,span=boundaries(text)
    outside=remove(text)
    name=settings['publicKey'].split(':',1)[0]+':'
    for line in outside.splitlines():
        line=line.split('#',1)[0]
        if '=' in line and line.split('=',1)[0].strip() in ('trusted-public-keys','extra-trusted-public-keys'):
            for key in line.split('=',1)[1].split():
                if key.startswith(name) and key!=settings['publicKey']:
                    raise PlatformError('another key with the station name exists outside the managed block')
    if span is not None:return ''.join(lines[:span[0]])+rendered+''.join(lines[span[1]:])
    return text+('' if not text or text.endswith('\n') else '\n')+rendered


def install(settings, *, uninstall=False, target=TARGET):
    if os.geteuid()!=0:raise PlatformError('install/remove requires root to update nix.custom.conf')
    if target.is_symlink():raise PlatformError('refusing to replace a symlinked custom configuration')
    existing=target.read_text() if target.exists() else ''
    if target.exists():
        info=target.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=ROOT_UID or info.st_mode & 0o022:
            raise PlatformError('custom configuration must be a root-owned regular file, not group/world writable')
    changed=remove(existing) if uninstall else update(existing,settings)
    if changed==existing:return {'changed':False,'target':str(target)}
    if target.exists():
        backup=target.with_name(target.name+'.crt-backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        shutil.copy2(target,backup);backup.chmod(0o600)
    else:backup=None
    fd,pending=tempfile.mkstemp(prefix='.crt-nix-',dir=target.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o644)
            stream.write(changed);stream.flush();os.fsync(stream.fileno())
        os.replace(pending,target);sync_dir(target.parent)
    finally:
        if os.path.exists(pending):os.unlink(pending)
    return {'changed':True,'target':str(target),'backup':str(backup) if backup else None}


def verify(settings):
    """Use configured substituters/trust in an empty store, with compilation off."""
    if os.geteuid()!=0:raise PlatformError('fresh-store verification requires root')
    path=settings['verificationPath']
    if not re.fullmatch(r'/nix/store/[0-9abcdfghijklmnpqrsvwxyz]{32}-[A-Za-z0-9+._?=-]+',path):
        raise PlatformError('invalid verification store path')
    nix='/nix/var/nix/profiles/default/bin/nix'
    env=dict(os.environ)
    for key in ('NIX_CONFIG','NIX_REMOTE','NIX_PATH','NIX_CONF_DIR'):env.pop(key,None)
    env['NIX_USER_CONF_FILES']='/dev/null'
    result=subprocess.run([nix,'config','show','--json'],capture_output=True,text=True,check=True,env=env)
    actual=json.loads(result.stdout)
    if settings['publicKey'] not in actual['trusted-public-keys']['value'] or not actual['require-sigs']['value']:
        raise PlatformError('system signing trust is not installed with signatures required')
    if not any(value.startswith(settings['url'].rstrip('/')+'/') for value in actual['substituters']['value']):
        raise PlatformError('station is not in system substituters')
    with tempfile.TemporaryDirectory(prefix='crt-station-cache-') as directory:
        subprocess.run(['/nix/var/nix/profiles/default/bin/nix-store','--store','local?root='+directory,
                        '--realise',path,'--option','max-jobs','0','--option','builders',''],
                       check=True,env=env,timeout=180)
        output=Path(directory)/path.lstrip('/')
        checksums=output/'SHA256SUMS'
        if not checksums.is_file():raise PlatformError('OSPI verification bundle lacks SHA256SUMS')
        verified=[]
        for line in checksums.read_text().splitlines():
            digest,name=line.split(maxsplit=1);name=name.lstrip('*')
            if name not in ('tiboot3.bin','tispl.bin','u-boot.img','fitImage.itb'):
                raise PlatformError('unexpected OSPI checksum file entry')
            with (output/name).open('rb') as stream:
                actual_digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual_digest!=digest:
                raise PlatformError('OSPI checksum failed: '+name)
            verified.append(name)
        if set(verified)!={'tiboot3.bin','tispl.bin','u-boot.img','fitImage.itb'}:
            raise PlatformError('incomplete OSPI checksum list')
    return {'automaticSubstitution':True,'signaturesRequired':True,'compiled':False,
            'publicTrustFromSystemConfig':True,'checksums':verified,'temporaryStoreRemoved':True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('show','install','remove','verify'))
    parser.add_argument('--config',required=True)
    parser.add_argument('--restart-daemon',action='store_true')
    args=parser.parse_args(argv)
    try:
        settings=json.loads(Path(args.config).read_text())
        if args.action=='show':print(block(settings));return 0
        if args.action=='verify':print(json.dumps(verify(settings),indent=2));return 0
        if args.restart_daemon and sys.platform!='darwin':
            raise PlatformError('automatic restart is supported only on this Determinate Mac')
        result=install(settings,uninstall=args.action=='remove')
        if args.restart_daemon:
            subprocess.run(['/bin/launchctl','kickstart','-k','system/systems.determinate.nix-daemon'],check=True)
            result['daemonRestarted']=True
        print(json.dumps(result,indent=2));return 0
    except (PlatformError,OSError,ValueError,KeyError,subprocess.SubprocessError) as error:
        print(f'client cache: {error}',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
