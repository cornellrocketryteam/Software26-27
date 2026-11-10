# Ground-station NixOS foundation

This is an initial configuration scaffold, **not a ready-to-install UM560 image**.
The physical target rejects activation/building a system until inspected root
mounts/bootloader settings and `groundStation.hardwareConfigured` are supplied.
It does not guess disk names, network interfaces, USB IDs, cache keys or secrets.

Current flake outputs:

- `nixosConfigurations.ground-station`: physical x86-64 target with install gate.
- `nixosConfigurations.ground-station-vm`: separate virtual evaluation/test target.
- `nixosModules.ground-station`: reusable modules.
- `checks.x86_64-linux.ground-station-vm`: VM test derivation; evaluation alone is
  not evidence that the VM booted. Running it needs a suitable Linux test worker.

## Present behavior

The foundation enables key-only non-root administrator SSH, scoped networking,
persistent journals, and a local offline landing page. Its `/healthz` is liveness;
`/readyz` deliberately returns 503 because the operational stack is not provisioned.
LAN interfaces must be explicitly configured; default SSH/web listeners are loopback.

The cache is off until a runtime signing-key path is configured. Harmonia signs
HTTP metadata; `nix.settings.secret-key-files` also signs newly built store outputs
for signature-checked SSH transfers. It does not retroactively sign existing paths.
Clients need the matching trusted public key. No key is generated or committed.

Station builds and ARM emulation are disabled until explicitly validated, and
field mode inhibits new heavy builds. CPU/RAM limits apply to the daemon actually
building. An opt-in untrusted SSH worker endpoint now exists, disabled by default;
see [worker setup and acceptance](../../../docs/operations/build-worker.md).
Changing field mode does not terminate builds already running. Live containment
and scheduling checks remain required before enabling remote builds.

Grafana has an optional native module requiring a runtime secret and reviewed
URL, but database/broker/datasource/dashboard provisioning, pinned OCI archives,
offline tiles and kiosk startup remain pending. Commanding is disabled until an
inspected device and endpoint are configured; legacy button firmware is limited
to monitoring. See [the listener gate](../../../ground-station/LaunchButton/README.md).

No automatic updates or deployment is installed. Remote health/admission is
available through the disabled-by-default worker module. An opt-in
SSH ingestion/receipt module is available but disabled by default. It requires
explicit public keys, an archive ID, enabled signed cache and review of effectively
administrative Nix access. See [cache setup and acceptance](../../../docs/operations/build-cache.md).
The CLI acknowledges only a matching durable receipt; successful copying alone
leaves publication pending. Local output roots remain after acknowledgement.

## Evaluation checks

From repository root:

```sh
nix eval --json --offline --impure --expr 'let f = builtins.getFlake (toString ./.); in import ./tests/platform/test_nixos_foundation.nix { nixpkgs = f.inputs.nixpkgs.outPath; }'
nix eval --raw .#nixosConfigurations.ground-station-vm.config.system.build.vm.drvPath
```

The first command requires the locked Nixpkgs source already available locally.
It checks the installation, signing, resource, networking and command-policy gates;
it does not build or boot a complete system.

Follow the [approved roadmap](../../../docs/superpowers/plans/2026-11-09-ground-platform.md)
for hardware inventory, service migration, cache/builder admission, and acceptance.
