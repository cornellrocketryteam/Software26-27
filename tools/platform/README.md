# Build/cache CLI foundation

Run from any directory using the repository's `scripts/platform`. Python 3.10+
and the standard library are sufficient. Import using `tools.platform` so the
standard library `platform` module remains available. Nix, nix-store, Git and
(optionally) OpenSSH are subprocess executables, not Python dependencies.

```sh
./scripts/platform check
./scripts/platform build fill-station --vehicle liquid --artifact release --builder auto
./scripts/platform build fill-station --vehicle hybrid --artifact fit --builder local --offline
./scripts/platform build fill-station --vehicle liquid --artifact fit --build-platform x86_64-linux --builder station
./scripts/platform build ground-station --builder station
./scripts/platform cache-sync
./scripts/platform status
./scripts/platform --config /absolute/path/to/config.json build fill-station --vehicle liquid --dry-run
```

`--config` is a global option, before the command. `--artifact` defaults to
`release`; `release` builds `sd`, `ospi`, `data` from one frozen source. OSPI
contains the FIT. Individual `fit`, `sd`, `ospi`, `data` are supported. No
`deploy` or `prepare-offline` command is advertised or implemented. Invalid
commands return nonzero. `status` reports local build/publication information,
not board health or activation. No operation reboots, flashes or deploys.

## Files and configuration

Default state is `$XDG_STATE_HOME/cornell-rocketry/platform`, or
`~/.local/state/cornell-rocketry/platform` when XDG_STATE_HOME is unset.
`CRT_PLATFORM_STATE_DIR` overrides the complete state path (also useful for tests).
Configuration defaults to `STATE/config.json`. A missing default means empty
configuration; an explicitly supplied missing or malformed file fails.
Configuration is never generated, guessed from a hostname, or written by the CLI.
There are no built-in SSH keys, public cache trust keys, or private credentials.

Empty `{}` configuration permits local builds and durable queuing. With an
existing, independently verified known_hosts file, optional configuration is:

```json
{
  "policy": {
    "preferStation": false,
    "probeTimeoutSeconds": 10,
    "evaluationTimeoutSeconds": 300,
    "copyTimeoutSeconds": 120,
    "receiptTimeoutSeconds": 300,
    "buildTimeoutSeconds": 14400
  },
  "station": {
    "validated": false,
    "platforms": ["aarch64-linux"],
    "store": "ssh-ng://builder@groundstation.example.org",
    "sshTarget": "builder@groundstation.example.org",
    "knownHosts": "/absolute/path/to/verified_known_hosts",
    "minFreeBytes": 100000000000
  },
  "cache": {
    "store": "ssh-ng://ingest@groundstation.example.org",
    "sshTarget": "ingest@groundstation.example.org",
    "knownHosts": "/absolute/path/to/verified_known_hosts",
    "receiptArchiveId": "reviewed-station-archive-v1"
  }
}
```

The example deliberately leaves station building disabled. Do not set validated
or preferStation until the selected platform and routing are demonstrated and
benchmarked. `platforms` are build platforms, not merely the station's host CPU.
The wrapper never configures global Nix settings, daemon SSH credentials,
substituters or signature trust. Configure the signed HTTP cache/trust separately;
`cache.store` here is the authenticated ingestion endpoint, not the HTTP URL.
SSH uses batch mode, strict host verification, no user SSH config, explicit host
and username, bounded connection/keepalive settings and an outer process timeout.
Existing SSH-agent authentication is used; no private key is copied or recorded.
Evaluation/preflight has its own 300-second default (maximum 3600), separate from
the 10-second health-probe default (maximum 60), so normal Nix evaluation is not
cut off by a network probe deadline.
`cache.receiptArchiveId` must match the station's configured archive identity.
Leave it absent for an older endpoint: copies remain pending rather than accepting
an unverified acknowledgement. Receipt exchange has a separate 300-second timeout
(maximum 3600). See [station setup and acceptance](../../docs/operations/build-cache.md).

## Routing and current build graphs

Default fill-station graph/platform remains `aarch64-linux`:

- Liquid: `mixosConfigurations.fill-station-liquid.config.system.build.*`
- Hybrid: `mixosConfigurations.fill-station.config.system.build.*`
- `sdImage`, `fitImage`, `ospiImage`, `dataCardImage` are existing attributes.

Explicit `--build-platform x86_64-linux` selects the parent's
`mixosBuildConfigurations."x86_64-linux".<machine>.config.system.build.*` graph.
The manifest records the selected build platform. Neither this option nor a
successful evaluation establishes that an image works on hardware.
Ground station always uses x86 and
`nixosConfigurations.ground-station.config.system.build.toplevel`; that physical
target is gated until inspected hardware and boot configuration are supplied.

Local preflight checks the Nix store daemon and configured native/extra platforms
or external-builder system declarations. This preserves the signed-in Determinate
external builder without assuming `max-jobs=0` overrides its priority. It does
**not** prove VM startup, offline credentials, or actual compilation capability.
Inherited conventional SSH `builders` are suppressed per invocation so a missing
station cannot become globally mandatory. Other SSH build workers are not yet
supported. Local mode leaves external builders and online substituters intact.

Auto is laptop-first unless `policy.preferStation` is exactly true. It considers
a validated station if local capability/preflight fails. A station requires
`validated: true`, the selected platform in its configuration, pinned SSH identity,
and a successful health protocol. Explicit station mode reports missing/invalid
configuration as an error. Offline rejects explicit station and only considers
local execution. The default station has never been contacted or validated.

A station build uses `nix build --store ssh-ng://... --no-link`, then copies the
result into the local store and registers permanent local roots. It does not
create a local filesystem out-link in the remote store. A remote GC race during
that unrooted build/copy interval is a surfaced failure, never an acknowledged
release; server-side build retention remains integration work. Remote worker
isolation, scheduling and actual external-builder behavior require station tests.

Only selection/preflight infrastructure failure can switch workers. Once Nix
starts evaluating/building the snapshot, any failure surfaces with its stderr and
retained log; no compiler error, missing attribute or invalid derivation triggers
another compilation elsewhere. Mid-build infrastructure failover is deliberately
not implemented in this foundation.

## Health command contract for the NixOS owner

Install a controlled `crt-platform-builder-health-v1` command for the configured
builder SSH account before marking the station validated. Invocation is exactly:

```text
ssh [strict pinned options] -- user@host crt-platform-builder-health-v1
```

Return one JSON object on stdout, diagnostics on stderr, nonzero on failure:

```json
{"protocol":1,"platforms":["aarch64-linux"],"available":true,"operationalMode":"maintenance","freeBytes":200000000000}
```

The station must calculate available/freeBytes and advertise only exercised
platforms. Field mode, busy workers, insufficient disk, unknown platforms, invalid
JSON, command failure and timeout all reject the worker. A future health helper
must enforce the same availability policy when work is actually scheduled; a
probe alone cannot reserve resources or enforce cgroup isolation. This repository
foundation defines the client; it does not install the command or a receipt server.

## Durable source, release and outbox

Each release gets a UTC/UUID ID. `STATE/sources/ID/` is a copy of the tracked
working files, including staged/unstaged bytes, executable modes and symlinks;
tracked deletions remain deleted. All selected artifacts build from this one
`path:` flake snapshot using the existing lock, without writing/updating the lock.
Untracked files are excluded and listed in the manifest; add intended source
files to Git before building. Submodules currently fail clearly. The snapshot is
retained even for clean builds; its SHA256 covers paths, modes, kinds and contents.
Dirty work is classified `development`; a clean build is only a `candidate`.
Neither classification means tested or active.

`outputs/platform/ID/` holds artifact links and a manifest link. The authoritative
manifest is `STATE/releases/ID/manifest.json`, so deleting output links cannot
remove release history or GC protection. SHA256/size inventories stream file
contents. Symlink inventory hashes/sizes describe the link target text and
`kind` explicitly distinguishes them from file bytes; this matters for NixOS
system closures. Versioned schema is `shared/schemas/release-manifest.schema.json`.
Bootloader version remains null and tests empty until real build-specific evidence
is supplied; host test results are not copied into hardware release claims.

Every successful artifact is rooted using:

```text
nix-store --add-root STATE/roots/ID/KIND --indirect --realise STORE_PATH
```

This is a collector registration operation, not just a manifest field or ordinary
symlink. Roots never move. Local Nix build out-links also pin partial builds.
The durable manifest is a write-ahead record: if the process dies after writing it
but before enqueuing, the next cache-sync/build reconstructs the pending outbox.
Failed/partial builds retain source/logs/roots for inspection, but do not receive
a completed manifest. There is currently no pruning or automatic orphan cleanup.
Only final output closures are retained; `preparedInputsRetained: false` explicitly
states that these roots do not protect discarded compiler/source dependencies.

Outbox entries live in `STATE/outbox/ID.json`, with immutable manifest digest,
store paths, GC roots, attempts and a current pending reason. Writes use atomic
rename and file/directory fsync. A sync lock serializes transfers; a separate short
outbox lock protects local writes, with a consistent lock order. Network I/O does
not hold the outbox lock, and enqueue never recursively acquires it. Lock waits
are bounded and return a visible retry/busy error. Concurrent builds have distinct
IDs/roots. Every normal build retries old records once before building and the new
record once afterward. `cache-sync` retries pending records. Both survive process
restarts. `--dry-run` performs no subprocess or filesystem writes (it may read
configuration/status); a build dry run does not establish availability/success.

## Publication and durable receipts

Publishing runs `nix copy --to CONFIGURED_SSH_NG_STORE STORE_PATH...` with pinned
SSH options and a timeout. Failed/partial copies leave the successful local build
and its pending pins intact. Repeating nix copy is idempotent at store-path level.
Manifest/root mismatch blocks publication. A cache outage does not change build
success to failure after durable enqueue; inspect status for the reason.

After a successful copy, clients with a pinned `receiptArchiveId` send a bounded
JSON request to exactly `crt-platform-cache-receive-v1` over the same pinned SSH
endpoint. There are no caller-selected server commands. The request includes
protocol 1, release ID, manifest SHA256, base64 of the exact manifest bytes and
the sorted store-path set. Limits are 1 MiB per manifest, 2 MiB per request and
64 distinct output paths.

The receiver rejects unsafe IDs, non-store paths, mismatched metadata and
conflicting duplicate releases. Under its archive lock it saves the original
manifest, registers indirect GC roots for all output closures, verifies content
with `nix store verify --recursive --no-trust`, then persists a receipt before
replying. `--no-trust` skips source-signature checks, not content hashing: the
reviewed importer is an administrative publisher. HTTP readers still require
the configured cache's signatures. No compilation or repair is requested.

A retry re-registers roots and verifies contents, returning the same saved receipt.
Failed validation, copy, verification, persistence or SSH exchange leaves the local
record pending. The client requires exact agreement on archive identity, release
ID, manifest digest, paths and retention-root mapping; an exit status alone is
insufficient. A valid receipt atomically changes the existing outbox record from
`pending` to `acknowledged`. There is no deletion/re-enqueue gap, and the immutable
manifest's `publication.statusSource` continues to point at that durable record.
Its original `publication.state` records the initial intent and is not rewritten.

`status` returns separate `pending` and `acknowledged` lists. `cache-sync` reports
remaining pending entries and the total number of locally recorded acknowledgements,
not just new ones. Zero exit means the queue was processed; inspect those fields.
Acknowledged records are not recopied on later builds/sync. All local release roots
remain retained, including after acknowledgement; there is no automatic pruning.
Acknowledged does not mean tested, active or deployed, or an independent backup.

The receiver package and opt-in NixOS ingestion account now exist, but the actual
station is not configured or validated. The forced SSH interface is not a security
boundary against its daemon-trusted developers: enabling it grants administrative
Nix capabilities and requires explicit keys/review. There is no HTTP upload route.

## Offline scope and troubleshooting

Offline mode disables substituters and conventional SSH workers and passes Nix's
`--offline`; it runs bounded evaluation/dry-run preflight before compilation.
Missing locked sources/attributes surface there with Nix's diagnostic. This is
not a `prepare-offline` implementation or a proof all fixed-output/build-time
inputs, network-using builders, VM credentials, OCI archives or maps are retained.
Already cached flake/evaluation inputs may be required even to enumerate missing
inputs. Fully isolated network/GC testing and comprehensive input closure retention
remain work in the approved broader plan.

- Unconfigured station: use local/auto, or provision/validate the health protocol,
  capability and known_hosts file. Do not set validation flags to suppress an error.
- Missing local platform: prepare the accepted Linux VM/external builder. `check`
  reports declared ARM compatibility; no board or remote SSH is performed.
- Publication pending: inspect `status`/outbox reason; retry `cache-sync` after
  connectivity returns. Check the installed receiver and matching pinned archive ID;
  a successful copy alone is not an acknowledgement.
- Corrupt JSON: status/sync return a named error and preserve the file for repair.
- Interrupted/failed build: inspect `STATE/logs/ID`; roots/sources are retained.
  Re-run explicitly after diagnosis. There is no automatic compiler rerun.
- Output links removed: state manifest and roots remain; cache-sync still works.
- Low space: inspect retained sources/roots and coordinate retention manually;
  there is no automatic GC that could discard recovery or pending releases.

## Host tests

```sh
python3 -m unittest discover -s tests/platform -p 'test_*.py' -v
```

The tests create isolated temporary Git repositories and real fake executable
files for Nix, nix-store and SSH. The programs model successful/failed builds,
external platform declarations, health timeouts/busy/full/field state, interrupted
copies, indirect GC registration and garbage collection. They never run a real
image build, connect to the station/board, activate a generation or flash hardware.
Actual Nix/store/network/hardware acceptance remains separate.
Receiver tests additionally exercise temporary archives, conflicting identities,
interrupted receipt writes and re-registration on retry. A separate manual check
has exercised the receiver against the previously built FIT using real local Nix;
it does not establish station SSH, signing, LAN substitution or physical power-loss
behavior.
