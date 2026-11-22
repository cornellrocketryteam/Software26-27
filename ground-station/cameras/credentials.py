#!/usr/bin/env python3
"""Initialize private credentials or render a private go2rtc config. Never log inputs."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

NAMES = ('fillcam0', 'fillcam1', 'fillcam2')


def validate(data):
    if set(data) != set(NAMES):
        raise ValueError('invalid cameras')
    for entry in data.values():
        if set(entry) != {'username', 'password'}:
            raise ValueError('invalid fields')
        for value in entry.values():
            if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
                raise ValueError('invalid credential')
    return data


def write_private(path, data):
    # Refuse replacement and symlinks; only a fully validated document is written.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(data, out)
        out.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--reference', required=True, type=Path)
    init.add_argument('--output', required=True, type=Path)
    render = commands.add_parser('render')
    render.add_argument('--credentials', required=True, type=Path)
    render.add_argument('--output', required=True, type=Path)
    render.add_argument('--port', type=int, default=1984)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            reference = json.loads(args.reference.read_text())
            data = {}
            for i, name in enumerate(NAMES):
                device = reference['devices'][f'fill-camera-{i}']
                # Deliberately resolve only this known reference, never arbitrary paths/URLs.
                if device['passwordRef'] != 'sharedSandboxPassword':
                    raise ValueError('unsupported password reference')
                data[name] = {'username': device['username'], 'password': reference['sharedSandboxPassword']}
            write_private(args.output, validate(data))
        else:
            credentials = validate(json.loads(args.credentials.read_text()))
            if not 1024 <= args.port <= 65535:
                raise ValueError('invalid port')
            streams = {name: 'rtsp://{}:{}@192.168.1.{}:554/Preview_01_main#transport=tcp'.format(
                quote(credentials[name]['username'], safe=''), quote(credentials[name]['password'], safe=''), 103 + i
            ) for i, name in enumerate(NAMES)}
            write_private(args.output, {
                'api': {'listen': f'127.0.0.1:{args.port}', 'allow_paths': ['/api/stream.mp4']},
                'rtsp': {'listen': ''},
                'webrtc': {'listen': '', 'ice_servers': [], 'candidates': []},
                'log': {'level': 'fatal'},
                'streams': streams,
            })
    except (ValueError, KeyError, TypeError, OSError):
        print('Camera credential operation failed; verify private input schema and output permissions.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
