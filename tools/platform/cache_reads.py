"""Read-only HTTP signature acceptance using fresh disposable client stores."""
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request

from .runtime import PlatformError


def store_path(value):
    if not isinstance(value, str) or not re.fullmatch(r'/nix/store/[0-9abcdfghijklmnpqrsvwxyz]{32}-[A-Za-z0-9+._?=-]+', value):
        raise PlatformError('invalid cache acceptance store path')
    return value


def corrupt(data, name):
    changed = False
    lines = data.decode().splitlines()
    for index, line in enumerate(lines):
        if line.startswith('Sig: '+name+':'):
            prefix, signature = line.rsplit(':', 1)
            if not signature: raise PlatformError('empty cache signature')
            lines[index] = prefix+':'+('B' if signature[0] == 'A' else 'A')+signature[1:]
            changed = True
    if not changed: raise PlatformError('expected signature missing from HTTP metadata')
    return ('\n'.join(lines)+'\n').encode()


def check(settings):
    if os.geteuid() != 0:
        raise PlatformError('cache read acceptance must run as root for its disposable local stores')
    fixture = store_path(Path(settings['fixtureFile']).read_text().strip())
    public = Path(settings['publicKeyFile']).read_text().strip()
    name = public.split(':', 1)[0]
    origin = settings['origin'].rstrip('/')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def fetch(path):
        with opener.open(origin+path, timeout=15) as response:
            data = response.read(4*1024*1024+1)
        if len(data)>4*1024*1024: raise PlatformError('fixture HTTP response exceeded its bound')
        return data
    metadata = fetch('/'+Path(fixture).name[:32]+'.narinfo')
    if any(line.startswith(b'CA:') for line in metadata.splitlines()):
        raise PlatformError('content-addressed fixture cannot prove signature enforcement')
    corrupt(metadata, name)  # require the expected station signature before testing clients
    env = dict(os.environ)
    for key in ('NIX_CONFIG','NIX_REMOTE','NIX_PATH'): env.pop(key, None)
    env['NIX_USER_CONF_FILES']='/dev/null'
    def command(args):
        return subprocess.run(args, capture_output=True, text=True, timeout=120, env=env)
    with tempfile.TemporaryDirectory(prefix='crt-cache-reads-') as directory:
        base=Path(directory)
        unrelated=command([settings['nixStore'],'--generate-binary-cache-key','unrelated-acceptance',
                           str(base/'unrelated.sec'),str(base/'unrelated.pub')])
        if unrelated.returncode: raise PlatformError('could not create unrelated disposable trust key')
        wrong=(base/'unrelated.pub').read_text().strip()
        class Proxy(http.server.BaseHTTPRequestHandler):
            def do_GET(self): self.respond(True)
            def do_HEAD(self): self.respond(False)
            def respond(self, body):
                try:
                    data=fetch(self.path)
                    if self.path.endswith('.narinfo'): data=corrupt(data,name)
                    self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers()
                    if body:self.wfile.write(data)
                except Exception: self.send_error(502,'Fixture upstream unavailable')
            def log_message(self,*args): pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Proxy)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            outcomes={}
            for label,key,source in [('trusted',public,origin),('unrelated',wrong,origin),
                                     ('corrupted',public,'http://127.0.0.1:'+str(server.server_port))]:
                root=base/label;root.mkdir()
                uri='local?root='+str(root)
                options=['--option','trusted-public-keys',key,'--option','secret-key-files','',
                         '--option','require-sigs','true','--option','substituters','',
                         '--option','builders','','--option','max-jobs','0','--option','flake-registry','']
                nix=[settings['nix'],'--extra-experimental-features','nix-command']
                config=command(nix+['config','show','--json',*options])
                if config.returncode: raise PlatformError('could not inspect disposable client policy')
                values=json.loads(config.stdout)
                for setting,expected in [('trusted-public-keys',[key]),('secret-key-files',[]),
                                         ('require-sigs',True),('substituters',[]),('max-jobs',0)]:
                    if values[setting]['value']!=expected: raise PlatformError('disposable client policy mismatch')
                result=command(nix+['copy','--from',source,'--to',uri,*options,fixture])
                artifact=root/fixture.lstrip('/')
                if label=='trusted':
                    if result.returncode: raise PlatformError('trusted signed fetch failed: '+result.stderr[-2000:])
                    dependency=store_path(str((artifact/'dependency').readlink().parent))
                    copied_dependency=root/dependency.lstrip('/')
                    if ((artifact/'payload').read_text()!='signed-cache artifact v1\n'
                            or (copied_dependency/'payload').read_text()!='signed-cache dependency v1\n'):
                        raise PlatformError('signed fixture contents or dependency differ')
                    outcomes[label]='complete closure fetched without compilation'
                else:
                    if not result.returncode or 'signature' not in result.stderr.lower() or artifact.exists():
                        raise PlatformError(label+' trust was not rejected specifically for its signature: '+result.stderr[-1500:])
                    outcomes[label]='rejected for signature'
            return {'scope':'signed-http-cache-reads','checks':outcomes,'publicKey':public,
                    'fixture':fixture,'disposableStores':True,'globalTrustChanged':False}
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)


def main(settings_path, argv=None):
    try:
        if (sys.argv[1:] if argv is None else argv):
            raise PlatformError('cache read acceptance takes no arguments')
        print(json.dumps(check(json.loads(Path(settings_path).read_text())),indent=2,sort_keys=True))
        return 0
    except (PlatformError,OSError,ValueError,subprocess.SubprocessError) as error:
        print(f'cache read acceptance: {error}',file=sys.stderr)
        return 1
