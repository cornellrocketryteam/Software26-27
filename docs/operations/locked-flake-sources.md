# Retaining locked flake sources for offline evaluation

Recipe/input pins retain build inputs, but Nix can still need locked dependency
source trees to evaluate a fresh checkout. `flake-inputs` inspects those source
trees separately, without evaluating/fetching the flake or compiling a target.

## Supported scope

This candidate supports version-7 lock files with immutable GitHub source inputs,
matching this repository's current lock. It computes each `source` store path from
its SHA256 `narHash` using local Nix hashing, checks local presence/registration,
and reports unknown input types rather than silently declaring them covered.
It inspects every non-root node, a conservative superset when follows/unused nodes
exist. It does not assume that references elsewhere in a build closure retain all
of Nixpkgs, MixOS, flake-parts or other evaluation sources.

The source checkout/root flake is deliberately separate: retain the matching Git
bundle/checkout and exact `flake.lock`. The report's lock digest identifies the
bytes inspected. Changing inputs requires inspection/pinning for that new lock.
No private runtime credentials or arbitrary evaluator state are captured.

## Later mini-PC commands

In the combined source checkout:

```sh
./scripts/platform flake-inputs --lock-file flake.lock
./scripts/platform flake-inputs --lock-file flake.lock --pin --dry-run
./scripts/platform flake-inputs --lock-file flake.lock --pin > "$HOME/flake-source-pin.json"
cat "$HOME/flake-source-pin.json"
./scripts/platform status
```

Run each after the previous succeeds. Without `--pin`, inspection is read-only;
`--dry-run` suppresses pinning even when requested. No source download, flake
archive, target evaluation/build, cache trust update or admission change occurs.
The installed command is `crt-platform`. Run on the machine that needs to evaluate
later: a Mac pin does not preserve the mini PC's store.

Exit 0 means all supported locked source paths were present/registered; exit 2
prints missing, unverified or unsupported sources; exit 1 prevents inspection or
pin completion. A passing inspection alone does not create roots. A requested pin
with a failing assessment is not created; inspect the JSON and exit status.

## When sources are missing

The helper does not fetch them. With authorized network access available, prepare
locked sources explicitly from the clean/recorded Git checkout, for example:

```sh
nix --extra-experimental-features 'nix-command flakes' flake archive \
  --store daemon --no-write-lock-file --no-update-lock-file --json \
  "git+file://$PWD" > "$HOME/flake-source-archive.json"
```

This is an online source-preparation operation and can download substantial source
trees. It is **not run by `flake-inputs`**, and it does not build the target system.
Use the tracked Git checkout reference shown here; do not archive the whole working
folder via `path:$PWD` when it contains build outputs, node_modules or other local
artifacts. Keep the lock unchanged. If resolution requires changing it, stop and
review that source change instead of updating it implicitly.

After explicit preparation, repeat inspection and pinning. A separately prepared
approved cache/store transfer is another option when it contains the exact source
paths; copying arbitrary replacement trees does not satisfy the lock. Rooting on
this host is not a portable export/import of all prepared inputs.

## What a source pin records

When requested and inspection passes, the tool creates an inert metadata-only
derivation containing the source references and lock digest, then uses the existing
verified `offline-pin` registration path. It rechecks the lock before mutation and
refuses a changed file. `flake-inputs.json` alongside the generic pin receipt records
the digest and node-to-store-path inventory. It never realizes the metadata object.

The pin uses the same eight-active-pin limit, partial-state handling and selected
`offline-unpin --pin-id ...` lifecycle described in [input pins](offline-input-pins.md).
No checkout or other pin is overwritten or evicted. A failed descriptor write can
leave a successfully registered generic root; inspect status before retrying or
releasing a selected partial attempt. Keep active state/root paths persistent.

Limits: lock files must be regular nonsymlink files, at most 1 MiB; at most 64
non-root inputs. Local hashing/registration uses bounded subprocesses and a
120-second inspection budget. There is no source-content rehash, Nix database
repair or arbitrary-flake evaluator validation. `offlineEvaluationValidated` and
`offlineBuildValidated` remain false even after retention.

## Acceptance evidence and remaining gates

Host tests cover supported/unknown input types, hashes, missing/unverified paths,
read-only mode, changed-lock refusal and a pin descriptor. Actual current-lock
inspection found seven of nine source trees missing on this development Mac;
none were fetched and no root was created for that incomplete set. A temporary
fixture using the already-present Nixpkgs/MixOS trees was pinned, checked and
explicitly released without downloads or compilation.

Later on the PC: prepare/pin the full locked set, verify the matching source bundle,
reboot and evaluate both recipes with network absent. Then run the separate
[static recipe audit](offline-input-audit.md), retain build inputs and complete a
normal contained network-isolated build. Source-tree presence/retention alone
proves none of those later steps.

Reference: [Nix flake source archiving](https://nix.dev/manual/nix/2.31/command-ref/new-cli/nix3-flake-archive).
