# Build cache publication and station acceptance

The build CLI, durable receiver and opt-in NixOS SSH ingestion module are
implemented. They have host tests, local real-Nix receiver evidence and isolated
signed-HTTP VM acceptance. The
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

## Signed HTTP VM acceptance

The manual `tests/platform/test_cache_vm.nix` boots the real ground-station
profile, nginx `/cache/` route and Harmonia. The guest has no NIC or forwarding.
Disposable signing keys are generated privately on its persistent disk before
the services start; production keys are not selected or created by this test.
The small fixture outputs are ordinary input-addressed derivations with a
dependency, so content-addressed trust exemptions cannot bypass the signature test.

Each client uses a fresh `local?root=...` store under the guest's private fixture
directory. Its inherited signing secrets and substituters are cleared,
`require-sigs` stays true, and builders are disabled. This separates clean-client
acceptance from files already present in the station's own store.

```sh
nix build --impure --expr 'let f = builtins.getFlake (toString ./.); pkgs = import f.inputs.nixpkgs { system = "aarch64-darwin"; }; in import ./tests/platform/test_cache_vm.nix { inherit pkgs; }' -o /private/tmp/ground-cache-vm --option timeout 2400 -L
```

Prepare the VM closure while online; running this guest requires no WAN, FlakeHub
credentials or fill-station connection. It is excluded from automatic branch-push
image workflows. A native Linux runner may select its matching host package set;
the guest stays x86. Budget 1.5 GiB guest RAM plus host overhead.

**Observed 2026-11-11: passed in 180 seconds**, exit status zero. Output:
`/nix/store/mk7ffc94afxzbharjvchrh51nya6k5rx-vm-test-run-ground-signed-cache`.

- A clean client fetched a correctly signed complete closure through nginx.
- Separate empty stores rejected an unrelated signing key and a deliberately
  corrupted signature with the correct public key trusted. Both failures had
  signature-specific diagnostics; no fixture path was accepted.
- GC ran only against the disposable client store. The explicitly rooted closure
  survived and a control object, confirmed present before GC, was removed.
- During cache outage, retained client files remained readable and the local
  operator page remained available; a new fetch failed. Restoring the cache allowed a fresh client fetch
  with no builder or external substituter.
- A populated-disk cold restart preserved public trust and recovered the cache
  automatically. Another empty client fetched with the original public key.
  `/readyz` stayed 503; telemetry, commanding and workers stayed disabled.

This verifies cache signing and client retention with small fixtures. It does not
prove physical LAN access, production key installation, SSH ingestion, two real
developers, station archive GC/backup, large release transfers, worker builds or
prepared-input offline rebuilding. The collector never targets the laptop or
station's normal store. See [implementation evidence](../superpowers/plans/2026-11-11-signed-cache-acceptance.md).
Trust behavior follows the [Nix signature settings](https://nix.dev/manual/nix/2.35/command-ref/conf-file.html)
and [copy verification](https://nix.dev/manual/nix/2.28/command-ref/new-cli/nix3-copy.html).

## Required physical and remaining acceptance

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
