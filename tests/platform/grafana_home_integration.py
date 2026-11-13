"""Disposable, NIC-free Grafana home-page smoke test using the real Nix environment."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment-json', type=Path, required=True)
    args = parser.parse_args()
    environment = json.loads(args.environment_json.read_text())
    pins = json.loads((ROOT / 'nix/nixos-configurations/ground-station/telemetry-images.json').read_text())
    grafana = pins['grafana']['imageName'] + '@' + pins['grafana']['imageDigest']
    client = json.loads((ROOT / 'tests/platform/telemetry_test_images.json').read_text())['client']
    prefix = 'crt-grafana-home-' + uuid.uuid4().hex[:12]
    created = []

    def docker(*command, data=None):
        result = subprocess.run(['docker', *command], input=data, capture_output=True, timeout=120)
        if result.returncode:
            raise RuntimeError('Disposable Grafana check: Docker operation failed.')
        return result.stdout.decode().strip()

    try:
        with tempfile.TemporaryDirectory(prefix='grafana-home-') as directory:
            work = Path(directory)
            spec = importlib.util.spec_from_file_location('runtime', ROOT / 'ground-station/provisioning/runtime.py')
            runtime = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(runtime)
            runtime.build_assets(ROOT / 'ground-station', work / 'assets')
            envfile = work / 'grafana.env'
            environment['GF_SECURITY_ADMIN_PASSWORD'] = secrets.token_urlsafe(32)
            fd = os.open(envfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                for key, value in sorted(environment.items()):
                    assert isinstance(value, str) and '\n' not in value
                    stream.write(key + '=' + value + '\n')
            client_name, grafana_name = prefix + '-client', prefix + '-server'
            docker('create', '--name', client_name, '--platform', 'linux/amd64', '--network', 'none',
                   '--pull', 'never', client, 'sleep', '3600')
            created.append(client_name)
            docker('start', client_name)
            docker('create', '--name', grafana_name, '--platform', 'linux/amd64', '--pull', 'never',
                   '--network', 'container:' + client_name, '--env-file', str(envfile), grafana)
            created.append(grafana_name)
            docker('cp', str(work / 'assets/grafana/dashboards'), grafana_name + ':/var/lib/grafana/dashboards')
            docker('start', grafana_name)
            probe = '''import json,time,urllib.request
for attempt in range(90):
 try:
  with urllib.request.urlopen('http://127.0.0.1:3000/grafana/api/dashboards/home',timeout=2) as response:
   model=json.load(response)
  assert model.get('dashboard',{}).get('title') == 'FillOps', 'Grafana home does not select FillOps'
  print('PASS: anonymous Grafana home selects FillOps on the pinned image, without a network adapter')
  break
 except AssertionError:
  raise
 except Exception:
  time.sleep(1)
else: raise RuntimeError('Grafana home did not become available')
'''
            result = subprocess.run(['docker', 'exec', '-i', client_name, 'python', '-'],
                                    input=probe, text=True, capture_output=True, timeout=120)
            if result.returncode:
                if 'Grafana home does not select FillOps' in result.stderr:
                    raise RuntimeError('Grafana home is reachable, but its dashboard title is not FillOps.')
                if 'Grafana home did not become available' in result.stderr:
                    raise RuntimeError('Grafana home endpoint did not become available.')
                raise RuntimeError('Grafana home fixture failed unexpectedly; details suppressed.')
            print(result.stdout.strip())
    finally:
        for name in reversed(created):
            subprocess.run(['docker', 'rm', '-f', '-v', name], capture_output=True, timeout=120, check=True)


if __name__ == '__main__':
    main()
