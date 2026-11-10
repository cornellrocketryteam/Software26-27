"""Build/cache command interface. Deployment is owned by a separate implementation."""
import argparse
import json
from pathlib import Path
import sys
from . import build, cache
from .builders import local_health
from .config import load_config, state_directory
from .runtime import PlatformError


def parser():
    cli = argparse.ArgumentParser(description='Ground platform build/cache foundation; never deploys.')
    cli.add_argument('--config', type=Path, help='explicit user JSON (default: STATE/config.json)')
    commands = cli.add_subparsers(dest='command', required=True)
    commands.add_parser('check', help='check local Nix capabilities; no image builds or SSH')
    builds = commands.add_parser('build', help='build and queue publication; never deploy')
    hosts = builds.add_subparsers(dest='host', required=True)
    for host in ('fill-station', 'ground-station'):
        sub = hosts.add_parser(host)
        if host == 'fill-station':
            sub.add_argument('--vehicle', choices=('liquid', 'hybrid'), required=True)
            sub.add_argument('--artifact', choices=(*build.ARTIFACTS, 'release'), default='release')
        else:
            sub.set_defaults(vehicle=None, artifact='system')
        sub.add_argument('--builder', choices=('auto', 'local', 'station'), default='auto')
        sub.add_argument('--build-platform', choices=('aarch64-linux', 'x86_64-linux'))
        sub.add_argument('--offline', action='store_true')
        sub.add_argument('--dry-run', action='store_true', help='print plan without subprocesses or writes')
    sync = commands.add_parser('cache-sync', help='retry publication; keep pins until durable receipt')
    sync.add_argument('--dry-run', action='store_true')
    commands.add_parser('status', help='read-only local build/outbox status (no target/deploy health)')
    return cli


def main(argv=None, *, repo=None):
    cli = parser()
    args = cli.parse_args(argv)
    repo = Path(repo).resolve() if repo else Path(__file__).resolve().parents[2]
    state = state_directory()
    if args.command == 'build' and args.host == 'ground-station' and args.build_platform == 'aarch64-linux':
        cli.error('ground-station requires x86_64-linux')
    try:
        config = load_config(args.config or state / 'config.json', explicit=args.config is not None)
        if args.command == 'build':
            result = build.execute(repo, state, config, args)
        elif args.command == 'cache-sync':
            records = cache.status(state) if args.dry_run else cache.sync(state, config)
            result = {'dryRun': args.dry_run, 'pending': records, 'acknowledged': 0}
        elif args.command == 'status':
            result = {'stateDirectory': str(state), 'pending': cache.status(state),
                      'receiptReceiver': 'not implemented; pending pins retained',
                      'tested': 'not tracked by this foundation', 'active': 'deployment owner tracks activation'}
        else:
            result = {'local': local_health(config, 'aarch64-linux'),
                      'station': 'not probed; explicit validated configuration required',
                      'scope': 'build/outbox/cache only'}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (PlatformError, OSError, ValueError) as exc:
        print(f'platform: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
