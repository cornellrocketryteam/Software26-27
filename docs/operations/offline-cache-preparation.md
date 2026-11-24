# Cache-only offline input preparation

`offline-prepare` fills missing static inputs from **one explicit HTTP(S) Nix
binary cache**, then re-audits. It never runs a target build, fixed-output fetch
builder, remote worker or system activation. It is the cache-copy stage of offline
preparation, not full automatic source fetching or proof of an offline build.

## Later operator workflow

Start with an evaluated recipe on the destination machine and an independently
verified cache public key. Set these variables to the selected cache's identity:

```sh
cache_url=REPLACE_WITH_APPROVED_CACHE_URL
cache_key=REPLACE_WITH_VERIFIED_PUBLIC_KEY
./scripts/platform offline-prepare --drv "$board_drv" \
  --cache-url "$cache_url" --public-key "$cache_key" --dry-run
./scripts/platform offline-prepare --drv "$board_drv" \
  --cache-url "$cache_url" --public-key "$cache_key" --pin > "$HOME/board-preparation.json"
cat "$HOME/board-preparation.json"
```

Run each command after the previous succeeds; use `"$pc_drv"` separately for the
PC recipe. Outside a checkout the installed command is `crt-platform`. Copy budgets
use `--copy-timeout-seconds` (1–3600, default 600), separate from bounded audits and
optional pin registration. Preview runs the local audit but performs no cache
requests, imports, roots or state writes. Actual preparation imports into the
explicit local daemon store. No global cache configuration or trust is installed.

The station cache's already recorded identity can be used when that cache actually
contains the needed inputs. Its inventory is not assumed complete. A PC usually
cannot restore paths missing from its store by asking its own store-backed cache;
choose an independently prepared source cache or restore missing inputs through
the reviewed online build workflow. A LAN cache can work without WAN, but the
cache host and requested paths still have to be available.

Nix may require an approved trusted identity or pre-enrolled daemon trust to accept
command-scoped public-key options/imports. This tool does not grant privileges,
use sudo, disable signature checking or mark a worker validated. Resolve actual
trust/permission errors through existing enrollment, not unsafe fallback flags.

## Copy policy and results

A fresh complete static graph is required. Missing derivation metadata must be
restored/evaluated first; unverified registration or dynamic/unresolved outputs
refuse preparation. Only known missing non-derivation paths are submitted to
`nix copy --from <selected-cache> --to daemon`. Source URLs containing credentials,
queries or fragments and malformed public keys are rejected by existing cache
configuration validation. No cache or key is guessed from a network address.

Copy uses `require-sigs=true`, the supplied public key, empty extra trusted keys,
empty substituters/builders, max-jobs zero and no substitution fallback. There is
no raw upstream URL fetching, compilation, catch-all cache scan or automatic retry
against another source. Nix's content-addressed-path rules still apply: requiring
signatures does not mean every content-addressed source needs a signer.

At most 4096 missing roots are planned, in batches of 32. Nix copies their reference
closures too, so path count is not a download-size/disk-space estimate. Transfers
have connect/stall limits and at most 300 seconds per batch within the copy budget.
The bounded command runner also limits output. Check actual disk capacity before
large preparation; no disk quota or rollback of completed imports is provided.

Result fields:

- `plannedPaths`: missing roots at the first audit.
- `copyAttempted`: at least one copy command started; `copied` means at least one
  whole batch completed. A failed batch can still have imported some data.
- `copyFailed` / `copyFailure`: incomplete copy or exhausted copy budget. Remaining
  paths may reflect cache absence, trust/permission failures or network errors;
  the result does not claim a specific cause without evidence.
- `newlyVerifiedPlannedPaths`, `remainingMissingPaths`, `unverifiedPaths`,
  `unresolvedOutputs`: final local static inventory evidence.
- `prepared`: copy commands completed (if needed) and the final static audit passed.
  This means the **static set**, not a successful build or all evaluation/runtime
  prerequisites. `offlineBuildValidated` remains false.
- `pin`: metadata-only retention receipt, only with `--pin` after preparation passes.

Exit 0 is a successful preview or complete static preparation; exit 2 is a produced
but incomplete preparation report; exit 1 prevents completion (invalid inputs,
audit/pin/tool error). Inspect exit-2 JSON instead of treating it as success.

Partial imports are not deleted or silently rolled back. Re-running audits first
and skips paths now present. Nothing is retained against GC until a complete
`--pin` succeeds or you explicitly use the separate pin workflow. GC between audit,
copy and pin can cause a safe refusal and need another attempt. A pin failure can
leave copied inputs and inspectable partial pin state: use `status` and the
[selected release guide](offline-input-pins.md), not broad cleanup.

## Remaining preparation work and acceptance

If the selected cache lacks a source/fetch result, this command stops short of
building it. Full upstream fetching under normal admitted builder policy, complete
locked-flake evaluation input retention and portable export/import of a prepared
input set remain separate work. Existing OCI archives/maps/private runtime files
are not invented or covered by a derivation audit.

Host tests cover preview isolation, explicit copy flags, no realization, failed
copy/no pin, malformed cache/key, unknown inventories, missing derivation refusal,
already-present inputs and CLI partial-result exit status. A real metadata-only
preview contacts only local Nix. Actual cache imports, signature rejection,
interrupted transfers, full mini-PC graphs, persistence and network-isolated
native builds remain pending; no real cache download occurred in this block.

References: [Nix closure copy](https://nix.dev/manual/nix/2.35/command-ref/new-cli/nix3-copy.html)
and [Nix signature/content-addressed policy](https://nix.dev/manual/nix/2.25/command-ref/conf-file#conf-require-sigs).
