"""Loopback-only FFmpeg -> synthetic RTSP source -> actual go2rtc -> MP4.

GO2RTC=/path/to/pinned/go2rtc FFMPEG=/path/to/ffmpeg python3 this_file.py
Only synthetic credentials; never opens a LAN or physical camera connection.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
GO2RTC = os.environ.get('GO2RTC', shutil.which('go2rtc'))
FFMPEG = os.environ.get('FFMPEG', shutil.which('ffmpeg'))


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_port(number, process):
    for _ in range(100):
        assert process.poll() is None, 'test process exited'
        try:
            with socket.create_connection(('127.0.0.1', number), timeout=.1):
                return
        except OSError:
            time.sleep(.05)
    raise AssertionError('test process startup timed out')


def main(browser_check=None):
    if not GO2RTC or not FFMPEG:
        raise SystemExit('Set GO2RTC to locked Nixpkgs 1.9.15 binary and FFMPEG to ffmpeg with libx264')
    children = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        source_port, api_port = port(), port()
        source_config = work / 'source.yaml'
        source_config.write_text(json.dumps({
            'api': {'listen': ''}, 'rtsp': {'listen': f'127.0.0.1:{source_port}'},
            'webrtc': {'listen': '', 'ice_servers': []}, 'log': {'level': 'fatal'},
            'streams': {'synthetic': []},
        }))
        credentials = work / 'credentials.json'
        credentials.write_text(json.dumps({name: {'username': 'synthetic', 'password': 'synthetic-only'}
                                          for name in ('fillcam0', 'fillcam1', 'fillcam2')}))
        relay_config = work / 'relay.yaml'
        subprocess.run([sys.executable, str(ROOT / 'ground-station/cameras/credentials.py'), 'render',
                        '--credentials', str(credentials), '--output', str(relay_config), '--port', str(api_port)], check=True)
        data = json.loads(relay_config.read_text())
        # Test-only source replacement. Production renderer has no host override.
        data['streams'] = {name: f'rtsp://127.0.0.1:{source_port}/synthetic#transport=tcp'
                           for name in data['streams']}
        relay_config.write_text(json.dumps(data))
        def start(command):
            child = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            children.append(child)
            return child
        try:
            source = start([GO2RTC, '-config', str(source_config)])
            wait_port(source_port, source)
            ffmpeg = start([FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error', '-re',
                            '-f', 'lavfi', '-i', 'testsrc2=size=160x120:rate=10', '-an',
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
                            '-pix_fmt', 'yuv420p', '-g', '10', '-f', 'rtsp', '-rtsp_transport', 'tcp',
                            f'rtsp://127.0.0.1:{source_port}/synthetic'])
            relay = start([GO2RTC, '-config', str(relay_config)])
            wait_port(api_port, relay)
            base = f'http://127.0.0.1:{api_port}'
            for route in ('/api/config', '/api/streams', '/api', '/api/restart'):
                try:
                    urllib.request.urlopen(base + route, timeout=2)
                except urllib.error.HTTPError as error:
                    assert error.code == 404, (route, error.code)
                else:
                    raise AssertionError(f'management route exposed: {route}')
            for name in ('fillcam0', 'fillcam1', 'fillcam2'):
                # Real source setup can race the FFmpeg RTSP ANNOUNCE; retry boundedly.
                for attempt in range(20):
                    assert ffmpeg.poll() is None, 'synthetic FFmpeg source failed'
                    try:
                        with urllib.request.urlopen(base + f'/api/stream.mp4?src={name}&video&audio=none', timeout=5) as response:
                            content = response.read(16384)
                            assert response.status == 200
                            assert response.headers.get_content_type() == 'video/mp4'
                            assert b'ftyp' in content and b'moov' in content and b'moof' in content and b'mdat' in content
                            decoded = subprocess.run([FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error',
                                                      '-i', 'pipe:0', '-frames:v', '1', '-f', 'null', '-'],
                                                     input=content, capture_output=True, timeout=10)
                            assert decoded.returncode == 0, 'relayed MP4 did not decode'
                        break
                    except urllib.error.HTTPError as error:
                        error.read()
                        if attempt == 19:
                            print('Synthetic relay response failed (test input only).', file=sys.stderr)
                            raise
                        time.sleep(.1)
            if browser_check is not None:
                browser_check(base)
            # Fresh connection recovers after a source outage without restarting relay.
            ffmpeg.terminate()
            ffmpeg.wait(timeout=5)
            replacement = start([FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error', '-re',
                                 '-f', 'lavfi', '-i', 'testsrc2=size=160x120:rate=10', '-an',
                                 '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
                                 '-g', '10', '-f', 'rtsp', '-rtsp_transport', 'tcp',
                                 f'rtsp://127.0.0.1:{source_port}/synthetic'])
            time.sleep(.5)
            with urllib.request.urlopen(base + '/api/stream.mp4?src=fillcam0&video&audio=none', timeout=8) as response:
                assert b'mdat' in response.read(16384)
            assert relay.poll() is None and replacement.poll() is None
            print('PASS: actual go2rtc, three RTSP->fragmented MP4 streams, management disabled, source reconnect')
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)


if __name__ == '__main__':
    main()
