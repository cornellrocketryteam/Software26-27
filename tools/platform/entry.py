"""Installed CLI entrypoint; source snapshots always refer to the user's checkout."""
from pathlib import Path
import sys

from . import cli
from .runtime import PlatformError, run


def checkout_root(directory):
    value = run(['git', '-C', str(directory), 'rev-parse', '--show-toplevel'], timeout=10).strip()
    root = Path(value)
    if not root.is_absolute() or not root.is_dir():
        raise PlatformError('build must run inside an existing project checkout')
    return root.resolve()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    args = cli.parser().parse_args(argv)
    try:
        repo = checkout_root(Path.cwd()) if args.command == 'build' else Path.cwd()
        return cli.main(argv, repo=repo)
    except (PlatformError, OSError, ValueError) as error:
        print(f'platform: {error}', file=sys.stderr)
        return 1
