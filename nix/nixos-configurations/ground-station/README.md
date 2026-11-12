# Ground-station NixOS foundation

This provides a UM560 foundation and a separate offline installer; the full
operational station is not provisioned. See the
[installation runbook](../../../docs/operations/ground-station-install.md).
The generic physical target rejects activation/building a system until inspected root
mounts/bootloader settings and `groundStation.hardwareConfigured` are supplied.
It does not guess disk names, network interfaces, USB IDs, cache keys or secrets.

Current flake outputs:

- `nixosConfigurations.ground-station`: physical x86-64 target with install gate.
- `nixosConfigurations.ground-station-um560`: inspected hardware foundation, with planned fresh filesystem labels.
- `nixosConfigurations.ground-station-installer`: separate live ISO embedding the UM560 closure.
- `nixosConfigurations.ground-station-vm`: separate virtual evaluation/test target.
- `nixosModules.ground-station`: reusable modules.
- `checks.x86_64-linux.ground-station-vm`: VM test derivation; evaluation alone is
  not evidence that the VM booted. Running it needs a suitable Linux test worker.

## Present behavior

The foundation enables key-only non-root administrator SSH, scoped networking,
persistent journals, and a local offline landing page. Its `/healthz` is liveness;
`/readyz` deliberately returns 503 because the operational stack is not provisioned.
LAN interfaces must be explicitly configured; default SSH/web listeners are loopback.
The UM560 profile matches Ethernet MAC `58:47:CA:7E:6E:15` to `lan0` (Ubuntu
called it `eno1`) and uses IPv4 DHCP without wait-online. Configure a router
reservation for the intended `192.168.1.206`; no static gateway is assumed.
It enables the packaged UI with field mode; other operational services stay off.

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

The operator UI has an optional prebuilt static package served by nginx, with
generated public configuration and explicit disconnected defaults. See
[operator UI startup](../../../docs/operations/operator-ui.md). `/readyz` remains
503 even when UI assets are available. No npm or device discovery runs at boot.

An opt-in [telemetry module](../../../docs/operations/telemetry-stack.md) now
loads pinned local OCI archives and provisions the database, broker, Grafana
datasource and dashboard. It requires three explicitly reviewed image pins and
private runtime credentials; no production versions are guessed. Native Grafana
must remain disabled when selecting that container stack. Production compatibility,
physical cold-boot acceptance remain pending, along with
prepared tile coverage and kiosk startup. Commanding is disabled until an
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

Use the [installation runbook](../../../docs/operations/ground-station-install.md)
for installation, console recovery and the confirmed physical checks.

## UM560 foundation build

```sh
nix build .#nixosConfigurations.ground-station-um560.config.system.build.toplevel
```

This profile expects new ext4 `/` labeled `CRT-GS-ROOT` and FAT `/boot` labeled
`CRT-GS-EFI`, with UEFI systemd-boot and AMD microcode/firmware. These are planned
labels, not claims about the existing Ubuntu partitions. Building formats nothing
and does not produce an installer. The separate installer output embeds this
closure and provides local console access/recovery. The operator confirmed SSD
boot, console login, Ethernet at 192.168.1.206, SSH, nginx health and the UI on
the physical UM560. Kiosk and operational service acceptance remain pending. SSH uses the existing contributor keys as `ground-admin`,
with root/password login disabled. The owner waived old Ubuntu/container backup
and restore. Future operational data/key retention remains a separate requirement.
