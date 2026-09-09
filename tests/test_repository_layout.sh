#!/usr/bin/env sh
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
"$repo_root/scripts/verify-repository-layout.sh" "$repo_root"
grep -Fq 'Flight software remains one shared Hybrid/Liquid codebase' "$repo_root/README.md"
grep -Fq 'Fill Station' "$repo_root/fill-station/README.md"
