# Build cache publication and station acceptance

The build CLI, durable receiver and opt-in NixOS SSH ingestion module are
implemented. They have host tests and local real-Nix receiver evidence. The
UM560 has not been configured: LAN substitution, two-developer access, daemon
containment, storage retention and offline operation still need live acceptance.

## Current local use

From the repository root:

```sh
./scripts/platform check
./scripts/platform build fill-station --vehicle liquid --artifact fit --builder local
./scripts/platform status
./scripts/platform cache-sync
```

No configured cache is required. A successful build is locally rooted, with a
manifest and pending publication record under the CLI state directory. Retrying
publication does not build, flash, reboot or activate a release. Use
`--artifact release` for SD, OSPI and DATA outputs from the same source snapshot.
See [CLI configuration](../../tools/platform/README.md) for state locations,
artifact links, builder selection, timeouts and offline limits.

## Station configuration prerequisites

1. Inspect hardware and boot configuration; preserve service/database backups
   before installing NixOS. The physical target is intentionally not install-ready.
2. Assign an explicit LAN address/name and interfaces, and verify the SSH host
   identity independently before pinning it in each developer's known-hosts file.
   Default SSH/web listeners remain loopback until the LAN is configured.
3. Provision the cache signing key outside Git and `/nix/store`, in a root-controlled
   directory with restrictive permissions. Configure its runtime path with
   `groundStation.cache.signingKeyFile`. Save the public key separately for clients.
   Do not place the secret in the importer-owned archive directory.
4. To enable ingestion, configure all of
   `groundStation.cache.ingestion.enable`, `authorizedKeys`, `archiveId` and
   `trustedDeveloperAccessReviewed`. Supply explicit bare public keys; existing
   administrator keys are not automatically inherited. Use an archive ID that
   clients can pin and retain with backups. Changing it for an existing archive
   is rejected rather than silently treating old data as a new archive.
5. Review that `ground-cache` is a Nix **trusted user**, which is effectively
   administrative access. Its forced SSH command restricts the supported interface;
   it is not a privilege boundary against those trusted developers. It admits only
   `nix-daemon --stdio` and `crt-platform-cache-receive-v1`, with no caller arguments,
   forwarding or TTY. Operations explicitly use the local daemon socket. Actual
   Linux cgroup/admission behavior must be tested before exposing build capability.
6. Keep station building disabled and field mode enabled during cache setup.
   Ingestion and HTTP reads do not establish that the station is a validated worker.

The fixed archive directory is `/var/lib/ground-cache-archive`, owned by
`ground-cache` with mode 0700. It contains archive identity, original manifests,
stable receipts and registered indirect roots. No automatic archive pruning or
GC is enabled. Monitor free disk space and keep database/archive backups separate.

## Developer configuration after station setup

Configure the signed HTTP cache URL and matching public trust key in the client's
Nix settings. Keep `require-sigs` enabled. The HTTP URL serves reads; it is not
an upload endpoint. The importer does not retroactively sign stored paths for
SSH export; prove HTTP substitution independently before relying on it.

Add the following `cache` section to the CLI's JSON configuration, substituting
the inspected station identity and an existing verified known-hosts file:

```json
{
  "cache": {
    "store": "ssh-ng://ground-cache@groundstation.example.org",
    "sshTarget": "ground-cache@groundstation.example.org",
    "knownHosts": "/absolute/path/to/verified_known_hosts",
    "receiptArchiveId": "reviewed-station-archive-v1"
  }
}
```

The hostname and archive ID above are examples, not discovered configuration.
Use a LAN-resolvable name/address for offline field operation. The archive ID
must equal the station's configured value. Authentication uses the existing SSH
agent; the CLI never copies private keys. An older endpoint without receipts can
omit `receiptArchiveId`; successful copies will remain unacknowledged.

Run `./scripts/platform cache-sync`, then inspect `status`. A release becomes
`acknowledged` only after the receiver saves its exact manifest, registers roots,
verifies the imported closure's content and durably saves a matching receipt.
Retries return that same receipt after revalidating retention. Copy completion
alone is insufficient. Failures remain pending and retain local roots.

The publication record stays at the immutable manifest's `statusSource` path;
its state changes atomically from pending to acknowledged. All local release
roots remain after acknowledgement. Acknowledged means retained at the recorded
archive at receipt time; it does not mean board-tested, active or independently
backed up. `cache-sync` reports the total local acknowledgement count.

## Required live acceptance

- Prove signed HTTP substitution from a clean client's store, and rejection of
  an invalid signature. Check host-level substituters as well as flake settings.
- Publish from two authorized developers. Verify unsupported SSH commands and
  unapproved keys are rejected. Reconnect/restart and compare stable receipts.
- Interrupt copy and receipt exchange separately. Confirm pending state survives,
  the next sync completes, conflicting release IDs fail and no build is replayed.
- In an isolated test store/archive, run GC and verify rooted closures survive.
  Never remove the only recovery release to test retention. Check archive and
  receipt restoration from an independent backup.
- Verify field-mode admission and actual daemon CPU/RAM containment on Linux.
  Do not infer these from evaluated settings or the forced-command wrapper.
- Test cache outage while services continue operating and a local build completes.
  Then prove another developer can reuse published outputs without recompilation.
- Complete separate prepared-input/offline rebuild tests. Output roots and a cache
  receipt do not protect every input needed for a future source rebuild.

## Host checks

```sh
python3 -m unittest discover -s tests/platform -p 'test_*.py'
nix eval --json --offline --impure --expr 'let f = builtins.getFlake (toString ./.); in import ./tests/platform/test_nixos_foundation.nix { nixpkgs = f.inputs.nixpkgs.outPath; }'
```

Tests use temporary archives and modeled Nix/store/SSH executables for failure
injection; they do not contact the station. A separate local check successfully
verified and rooted the previously built Liquid FIT using the real Nix daemon,
preserved exact manifest bytes and returned the same receipt on retry. That check
did not run a global GC, install NixOS, test WAN isolation or simulate power loss.
