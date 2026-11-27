"""Isolated optional EcoFlow collector; HTTP reads only cached sanitized state."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import time

FIELDS = ('batteryPercent', 'inputWatts', 'outputWatts')


class Monitor:
    def __init__(self, fetch, interval=30, clock=time.monotonic):
        if type(interval) is not int or not 30 <= interval <= 300:
            raise ValueError('Expected 30..300 second interval')
        self.fetch, self.interval, self.clock = fetch, interval, clock
        self.lock = threading.Lock()
        self.checked = None
        self.value = {'state': 'pending'}

    def tick(self):
        try:
            value = self.fetch()
            if not isinstance(value, dict) or value.get('state') not in ('cloud-snapshot', 'cloud-reports-offline'):
                raise ValueError('Invalid snapshot')
            if value['state'] == 'cloud-snapshot':
                for key in FIELDS:
                    metric = value.get(key)
                    maximum = 100 if key == 'batteryPercent' else 10000
                    if metric is not None and (type(metric) not in (int, float) or not math.isfinite(metric) or not 0 <= metric <= maximum):
                        raise ValueError('Invalid metric')
            value = {'state': value['state'], **{key: value.get(key) if value['state'] == 'cloud-snapshot' else None for key in FIELDS}}
        except Exception:
            value = {'state': 'unavailable'}
        with self.lock:
            self.value, self.checked = value, self.clock()

    def snapshot(self):
        with self.lock:
            value = dict(self.value)
            age = None if self.checked is None else max(0, self.clock() - self.checked)
        if age is not None and age > self.interval + 25:
            value = {'state': 'stale'}
        return {'enabled': True, 'readOnly': True, 'deviceSampleTimeKnown': False,
                'ageSeconds': age, 'state': value['state'],
                **{key: value.get(key) if value['state'] == 'cloud-snapshot' else None for key in FIELDS}}


def handler_for(monitor):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/v1/ecoflow':
                self.send_error(404)
                return
            raw = json.dumps(monitor.snapshot(), allow_nan=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', choices=('us', 'eu'), required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--credentials-file', required=True)
    parser.add_argument('--interval', type=int, default=30)
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    command = [sys.executable, str(Path(__file__).with_name('ecoflow_probe.py')),
               '--region', args.region, '--serial', args.serial,
               '--credentials-file', args.credentials_file, '--execute']
    def fetch():
        # Hard deadline includes DNS and a slow HTTP peer. No cloud response/error logging.
        result = subprocess.run(command, check=True, capture_output=True, timeout=20)
        return json.loads(result.stdout)
    monitor = Monitor(fetch, args.interval)
    stop = threading.Event()
    def collect():
        while not stop.is_set():
            monitor.tick()
            stop.wait(args.interval)
    threading.Thread(target=collect, name='ecoflow-cloud', daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(monitor))
    server.daemon_threads = True
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()


if __name__ == '__main__':
    main()
