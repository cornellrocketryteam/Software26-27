# Offline static-input audit

`crt-platform offline-audit` checks an already evaluated derivation against the
**local Nix daemon store**. It never builds, substitutes/downloads, contacts the
remote worker, enrolls accounts, creates GC roots, publishes or activates anything.
It is not `prepare-offline` and never certifies an offline build.

## Later mini-PC preflight

In the combined source checkout, evaluate the two exact recipes as in the handoff.
Then audit them separately:

```sh
./scripts/platform offline-audit --drv "$pc_drv" > "$HOME/pc-input-audit.json"
cat "$HOME/pc-input-audit.json"
./scripts/platform offline-audit --drv "$board_drv" > "$HOME/board-input-audit.json"
cat "$HOME/board-input-audit.json"
```

Use the printed `/nix/store/*.drv` values on the same machine that evaluated them.
The installed command is `crt-platform` rather than `./scripts/platform`. A Mac's
store is not the PC's store, even when both inspect the same source revision.
Derivation evaluation can itself fail offline if locked flake inputs are missing;
this command cannot enumerate a graph that does not exist locally. Prepare those
inputs while online first; do not enable network or compilation in the audit.

Exit codes: **0** means the supported static inventory was present and registered,
**2** means a report was produced with missing/unverifiable/unresolved inputs,
**1** means metadata/input/tool failure prevented the audit. Read JSON even for
exit 2. Do not chain the audit to deployment as a build-success gate: all reports
have `offlineBuildValidated:false`.

## What it checks

The audit reads recursive derivation metadata using offline Nix commands with
substituters and builders disabled and the daemon store explicitly selected.
It supports the legacy map, per-record version-4 map and version-4 envelope formats; other/unsupported
formats fail instead of silently treating unknown fields as an empty graph.

Inventory includes the full static graph's derivation files, source paths and
known fixed-output paths (including fetch results). Normal unbuilt compiler/
package outputs are not required to be present: those may be built from retained
inputs. Missing fixed outputs commonly identify online preparation still needed.
Unknown output addresses or dynamic inputs remain unresolved, not a passing check.
No derivation environment, URL, credentials or builder script is included in JSON.

- `missingPaths`: store objects absent on this filesystem.
- `unverifiedPaths`: present paths whose registration batch could not be verified,
  or whose check exceeded the overall time budget. A daemon/permission failure is
  not relabelled as a missing source. One invalid path can leave its whole batch
  unverified; inspect further rather than assuming all batch members are absent.
- `inventory.unresolvedOutputs`: supported metadata exposed an address/dynamic
  dependency the static audit could not resolve.
- `assessment`: `missing_static_inputs`, `unverifiable`, or
  `static_inputs_present`. Unverifiable takes priority when conditions overlap;
  inspect all fields.

Registration is checked in batches of 128, capped at 20 seconds each and an
overall default budget of 120 seconds (`--timeout-seconds` allows 1–300).
The audit streams subprocess output with a 16 MiB stdout / 64 KiB stderr cap,
terminating the process group at the limit rather than spooling unbounded data
to disk. Graph/path counts
are bounded too. Oversized graphs fail explicitly and require a different,
reviewed inspection approach. The deadline is also checked during graph/path inspection. Individual local
filesystem calls cannot be interrupted by these cooperative checks; a stalled
filesystem can exceed the wall-clock budget before the tool reports exhaustion.
Filesystem presence and store registration do not
establish content integrity or signatures.

## What a passing static audit does not establish

This is a conservative full graph, not Nix's minimal realization plan: it can flag
inputs from a branch whose already-built output would avoid rebuilding it. It
never makes those inputs disappear or fetches them automatically. Conversely,
a present graph does not prove compiler capability, builder admission, runtime
credentials/OCI archives, network-free builder scripts, content integrity,
signature trust, enough disk/RAM, successful output generation or deployability.
No GC roots are added, so GC can remove inputs immediately after the audit.

Retain and transfer prepared inputs through the separately reviewed build/cache
workflow. The acceptance gate remains an actual successful build with network
isolation, retained inputs, the correct machine and normal builder containment.
Do not change `validated` flags or bypass admission just because this audit passes.
This block does not implement full input preparation, GC retention or the final
network-isolated hardware test.

Host tests cover both metadata formats, fixed-output address fallback, missing
paths, registration failures, dynamic/unknown metadata, incomplete graphs, CLI
exit status and absence of realization commands. A real inert local fixed-output
derivation was correctly reported missing without realization. Full PC/board
closure audits and offline native builds remain pending.

Format references: [Nix derivation JSON](https://nix.dev/manual/nix/2.35/protocols/json/derivation/index.html)
and [recursive derivation inspection](https://nix.dev/manual/nix/2.32/command-ref/new-cli/nix3-derivation-show).


After a passing static audit, the separate explicit
[offline-pin command](offline-input-pins.md) can retain those checked paths.
The audit itself remains read-only and adds no roots.
