"""Explicit, read-only EcoFlow developer-cloud enrollment probe. No output controls."""
import argparse
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import time
import urllib.parse
import urllib.request

HOSTS = {'us': 'api.ecoflow.com', 'eu': 'api-e.ecoflow.com'}
LIMIT = 1024 * 1024


class ProbeError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError('Cloud redirect refused')


def read_credentials(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
            raise ProbeError('Credentials must be an owner-only regular file owned by this user')
        raw = stream.read(8193)
    if len(raw) > 8192:
        raise ProbeError('Credentials file too large')
    value = json.loads(raw)
    for key in ('accessKey', 'secretKey'):
        if not isinstance(value.get(key), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,512}', value[key]):
            raise ProbeError('Invalid developer credentials')
    return value


def signed_request(region, credentials, endpoint, params, nonce, timestamp):
    query = '&'.join(f'{key}={params[key]}' for key in sorted(params))
    suffix = f'accessKey={credentials["accessKey"]}&nonce={nonce}&timestamp={timestamp}'
    payload = (query + '&' if query else '') + suffix
    signature = hmac.new(credentials['secretKey'].encode(), payload.encode(), hashlib.sha256).hexdigest()
    return urllib.request.Request(
        f'https://{HOSTS[region]}/iot-open/sign/device/{endpoint}' + ('?' + urllib.parse.urlencode(params) if params else ''),
        headers={'accessKey': credentials['accessKey'], 'nonce': str(nonce), 'timestamp': str(timestamp), 'sign': signature},
        method='GET',
    )


def request(region, credentials, endpoint, params):
    req = signed_request(region, credentials, endpoint, params, secrets.randbelow(900000) + 100000, int(time.time() * 1000))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=5) as response:
            raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ProbeError('Cloud response too large')
        value = json.loads(raw)
        if not isinstance(value, dict) or str(value.get('code')) != '0':
            raise ProbeError('Cloud request rejected; check enrollment, region and system clock')
        return value.get('data')
    except ProbeError:
        raise
    except Exception:
        raise ProbeError('Cloud read failed; check connectivity, credentials and system clock') from None


def metrics(data):
    if not isinstance(data, dict):
        raise ProbeError('Invalid quota response')
    result = {}
    for name, key, maximum in (
        ('batteryPercent', 'bms_bmsStatus.soc', 100),
        ('inputWatts', 'pd.wattsInSum', 10000),
        ('outputWatts', 'pd.wattsOutSum', 10000),
    ):
        value = data.get(key)
        result[name] = value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum else None
    return result


def probe(region, credentials, serial, fetch=request):
    devices = fetch(region, credentials, 'list', {})
    if not isinstance(devices, list):
        raise ProbeError('Invalid enrolled-device response')
    matches = [item for item in devices if isinstance(item, dict) and item.get('sn') == serial]
    if len(matches) != 1:
        raise ProbeError('Serial is not uniquely enrolled in this developer account')
    online = matches[0].get('online')
    if type(online) not in (str, int) or str(online) != '1':
        return {'state': 'cloud-reports-offline', 'readOnly': True, 'deviceSampleTimeKnown': False}
    values = metrics(fetch(region, credentials, 'quota/all', {'sn': serial}))
    return {'state': 'cloud-snapshot', 'readOnly': True, 'deviceSampleTimeKnown': False,
            'receivedUnixMs': int(time.time() * 1000), **values}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', choices=HOSTS, required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--credentials-file')
    parser.add_argument('--execute', action='store_true', help='Perform two read-only cloud GETs')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9]{1,64}', args.serial):
        parser.error('Serial must be alphanumeric')
    if not args.execute:
        print(json.dumps({'execute': False, 'readOnly': True, 'region': args.region,
                          'requests': ['GET enrolled device list', 'GET selected device quota if online']}))
        return
    if not args.credentials_file:
        parser.error('--credentials-file required with --execute')
    try:
        print(json.dumps(probe(args.region, read_credentials(args.credentials_file), args.serial)))
    except (ProbeError, OSError, ValueError, TypeError):
        parser.exit(1, 'EcoFlow probe failed. Check private credential file, enrollment, region, connectivity and clock.\n')


if __name__ == '__main__':
    main()
