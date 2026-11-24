# Explicit local retention of prepared static inputs

`crt-platform offline-pin` retains already-present, freshly audited static inputs
against ordinary local Nix garbage collection. It does not prepare/download missing
inputs, compile a target, transfer to another machine, publish, activate a system
or enable a builder. A pin is not a successful offline-build result.

## Later mini-PC step

After the two recipes evaluate and their static audits pass, preview and then pin
one recipe at a time:

```sh
./scripts/platform offline-pin --drv "$pc_drv" --dry-run
./scripts/platform offline-pin --drv "$pc_drv" > "$HOME/pc-input-pin.json"
cat "$HOME/pc-input-pin.json"
./scripts/platform offline-pin --drv "$board_drv" --dry-run
./scripts/platform offline-pin --drv "$board_drv" > "$HOME/board-input-pin.json"
cat "$HOME/board-input-pin.json"
./scripts/platform status
```

Use the installed `crt-platform` name outside a checkout. Run each command only
after the previous succeeds, as the build/deployment user rather than sudo. All
pin operations use the local daemon explicitly. A pin on a Mac does not preserve
anything on the mini PC. Dry-run performs a fresh read-only audit but creates no
state, roots or receipt; it is not a cached report or a no-subprocess invocation.

Pinning refuses missing, unverified or unresolved static inputs. Use
[offline-audit](offline-input-audit.md) to inspect a refusal; it does not trigger a
fetch or relax admission to make the operation succeed.

## What is retained

The exact union of checked source paths, derivation files and known fixed-output
paths is referenced by an inert metadata-only derivation. `nix-instantiate`
registers its indirect GC root; **it is never realized**. The metadata object's
platform and nonexistent builder intentionally make it unsuitable as a runnable
artifact. Do not run `nix build`/`nix-store --realise` on it.

Before a success receipt is written the tool checks both that the registered root
exists and that its Nix reference closure contains every audited path. A receipt
records the original target derivation, metadata derivation, root, path count,
normalized inventory digest and timestamp. `offlineBuildValidated` remains false.
No system profile, SSH identity, cache signing key or normal worker policy changes.

Only the current daemon's reference graph is retained. Flake evaluation sources
that were not build inputs are not added implicitly. Preserve the evaluated recipes
and separately prepare locked evaluation inputs before relying on reevaluation.
Normal compiler/package outputs may still need to be built from the retained
inputs; this does not mean every build output already exists. Fixed-output fetch
results must already be present. Content integrity, signatures, credentials,
external builder behavior, disk/RAM and actual compilation remain separate checks.

## State, failures and capacity

Pins live in `offline-input-pins/<pinId>/` beneath the CLI state directory. Keep
that directory in stable persistent storage. Moving/deleting the root link or its
parent can remove GC protection. Removing a source checkout or ordinary build
artifact does not intentionally remove these separate pins. There is no automatic
pruning or eviction; at most eight pin directories, including partial attempts,
are allowed. Rooting existing large inputs can keep substantial disk space in use;
this command neither downloads new outputs nor promises a small retained closure.

Each directory contains `audit.json`, `pin.nix`, `root` and, only after verification,
`receipt.json`. Registration or receipt-write failures leave partial state intact
for inspection; do not assume an absent receipt means there is no live root.
Retries create a new pin rather than overwrite one. `status` lists recorded,
partial, invalid or missing/changed local root state. It explicitly does not
recheck daemon registration, content or the underlying build on every status call.

## Release a selected pin or partial attempt

After a replacement is retained and accepted, use the exact `pinId` from status
or a receipt in an explicit maintenance window:

```sh
./scripts/platform offline-unpin --pin-id REPLACE_WITH_EXACT_PIN_ID --dry-run
./scripts/platform offline-unpin --pin-id REPLACE_WITH_EXACT_PIN_ID
```

The dry-run reads local managed state only. The action refuses traversal,
symlinked directories, unexpected/changed root targets and conflicting archives.
It removes only the selected managed root symlink, archives that attempt under
`offline-input-pin-history/<pinId>` and frees its active slot. It does not delete
store data, invoke GC, remove other pins or drop another machine's roots. A later
ordinary GC can collect inputs if no other roots retain them. Keep every pin that
is still needed for offline work.

Partial attempts can be released the same way, including attempts where no root
was successfully created. Partial state is never silently discarded on failure.
If release fails after root removal, inspect status and retry only that selected
attempt; root protection must not be assumed. Released archives preserve history,
not retention. Metadata-history cleanup is separate; do not move active pin roots
as a workaround for the eight-pin capacity.

## Acceptance limits

Host fixtures cover dry-run isolation, refusal after failed audit, root/reference
verification, partial failure, symlink rejection capacity without eviction, special-file receipt rejection and selected release.
A real local two-source metadata fixture was instantiated, rooted and checked;
no compilation, download or garbage collection was performed. Its temporary test
root was removed with its fixture directory afterwards.

Actual mini-PC persistence/reboot, concurrent/interrupted GC behavior, full PC/board
input inventories and a successful network-isolated native build remain pending.
Use the [combined handoff](combined-return-handoff.md) for activation/deployment;
this command does not replace those gates.

Reference: [Nix instantiation and root registration](https://nix.dev/manual/nix/2.34/command-ref/nix-instantiate.html).
