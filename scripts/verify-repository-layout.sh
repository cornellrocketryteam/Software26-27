#!/usr/bin/env sh
set -eu

repo_root=${1:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
required_paths='README.md CONTRIBUTING.md docs/architecture/system-boundaries.md docs/interfaces/README.md docs/operations/development-readiness.md shared/proto/README.md fsw/README.md fill-station/README.md ground-station/README.md airbrakes/README.md rats/README.md blims/README.md payload/README.md nix/README.md'

for path in $required_paths; do
  if [ ! -e "$repo_root/$path" ]; then
    printf 'missing required repository path: %s\n' "$path" >&2
    exit 1
  fi
done
