"""Build/cache command interface. Deployment is owned by a separate implementation."""
import argparse
import json
from pathlib import Path
import sys
from . import build, cache, deploy, deploy_ssh
from .builders import local_health, probe_station
from .config import load_config, state_directory
from .runtime import PlatformError


def parser():
    cli = argparse.ArgumentParser(description='Ground platform build/cache tools with separate explicit FIT deployment.')
    cli.add_argument('--config', type=Path, help='explicit user JSON (default: STATE/config.json)')
    commands = cli.add_subparsers(dest='command', required=True)
    check = commands.add_parser('check', help='check local Nix; optional read-only station probe')
    check.add_argument('--station', action='store_true', help='explicitly probe configured pinned station; never build')
    check.add_argument('--build-platform', choices=('aarch64-linux', 'x86_64-linux'), default='aarch64-linux')
    builds = commands.add_parser('build', help='build and queue publication; never deploy')
    hosts = builds.add_subparsers(dest='host', required=True)
    for host in ('fill-station', 'ground-station'):
        sub = hosts.add_parser(host)
        if host == 'fill-station':
            sub.add_argument('--vehicle', choices=('liquid', 'hybrid'), required=True)
            sub.add_argument('--artifact', choices=(*build.ARTIFACTS, 'release'), default='ospi')
        else:
            sub.set_defaults(vehicle=None, artifact='system')
            sub.add_argument('--profile', choices=('foundation', 'um560', 'um560-services', 'um560-validation', 'um560-cache'), default='foundation',
                             help='ground-station system profile; never activates it')
        sub.add_argument('--builder', choices=('auto', 'local', 'station'), default='auto')
        sub.add_argument('--build-platform', choices=('aarch64-linux', 'x86_64-linux'))
        sub.add_argument('--offline', action='store_true')
        sub.add_argument('--dry-run', action='store_true', help='print plan without subprocesses or writes')
    deployment = commands.add_parser('deploy', help='explicitly verify and flash a release FIT; never builds or reboots')
    deployment.add_argument('--manifest', type=Path, required=True)
    deployment.add_argument('--target', required=True, help='explicit SSH alias or user@host with verified host identity')
    deployment.add_argument('--dry-run', action='store_true', help='verify local bytes and print plan without SSH or state writes')
    enrollment = commands.add_parser('deploy-ssh-init', help='prepare local deployment key and verified host pin; no network contact')
    enrollment.add_argument('--host-key', type=Path, required=True, help='independently verified ED25519 public host key file')
    enrollment.add_argument('--host', default='192.168.1.106', help='board IPv4 address')
    enrollment.add_argument('--dry-run', action='store_true')
    sync = commands.add_parser('cache-sync', help='retry publication; keep pins until durable receipt')
    sync.add_argument('--dry-run', action='store_true')
    resume = commands.add_parser('transfer-resume', help='resume retained worker requests/imports; never creates a new release')
    resume.add_argument('--dry-run', action='store_true', help='list journals without contacting the worker')
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
        elif args.command == 'deploy':
            result = deploy.execute(state, args)
        elif args.command == 'deploy-ssh-init':
            result = deploy_ssh.execute(args)
        elif args.command == 'cache-sync':
            records = cache.status(state) if args.dry_run else cache.sync(state, config)
            result = {'dryRun': args.dry_run, 'pending': records,
                      'acknowledged': len(cache.acknowledged(state))}
        elif args.command == 'transfer-resume':
            result = ({'dryRun': True, 'pending': build.transfer_status(state)} if args.dry_run
                      else build.resume_transfers(state, config))
        elif args.command == 'status':
            result = {'stateDirectory': str(state), 'pending': cache.status(state),
                      'workerTransfers': build.transfer_status(state),
                      'deployments': deploy.status(state),
                      'acknowledged': cache.acknowledged(state),
                      'receiptReceiver': 'protocol 1; requires pinned archive identity and installed receiver',
                      'tested': 'not tracked by this foundation', 'active': 'deployment owner tracks activation'}
        else:
            try:
                local = local_health(config, args.build_platform)
            except PlatformError as exc:
                if not args.station:
                    raise
                local = f'unavailable: {exc}'
            result = {'local': local,
                      'station': 'not probed; explicit validated configuration required',
                      'scope': 'build/outbox/cache only'}
            if args.station:
                result.update(station=probe_station(config),
                              stationValidated=config.get('station', {}).get('validated') is True,
                              requestedBuildPlatform=args.build_platform)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (PlatformError, OSError, ValueError) as exc:
        print(f'platform: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
