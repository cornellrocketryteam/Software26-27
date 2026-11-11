# NixOS telemetry stack preparation and startup

The opt-in telemetry module packages TimescaleDB/PostgreSQL 17, EMQX and Grafana
as supervised containers. It loads prepared Linux/amd64 archives from the Nix
system closure and uses `--pull never`. Building is a preparation step; startup
does not fetch images, install plugins or require a fill-station connection.

The current Compose installation remains the migration baseline. Nothing in this
increment activates production services, replaces their volumes or changes a physical device.
Do not enable the new stack against the existing data directories without the
inventory, backup restore and compatibility checks below.

## Inventory before choosing production pins

The Compose file's `latest` tags do not identify installed versions. On the
existing host, record the three running container image IDs and repository digests
without dumping their environment or complete inspect output:

```sh
docker inspect --format '{{.Name}} {{.Config.Image}} {{.Image}}' emqx timescaledb grafana
```

For each recorded image ID, inspect `RepoDigests`, OS and architecture only.
Record PostgreSQL server and Timescale extension versions, the actual database
name, EMQX version/edition/license metadata and stable node name, all broker rules,
and Grafana version/datasource/dashboard identity. Capture an admin export and a
database-consistent backup; restore into an isolated instance before migration.
Keep tokens, passwords, license keys and full environment dumps outside the repo.

The broker helper follows the officially versioned **EMQX Enterprise 5.8.8** API
contract. That edition provides Schema Registry and the PostgreSQL action; the
corresponding Community build excludes them. A production image requires reviewed
capabilities and a suitable license, not just a successful container start.
Sources: [edition exclusions](https://github.com/emqx/emqx/blob/e5.8.8/rebar.config.erl),
[Schema Registry API](https://github.com/emqx/emqx/blob/e5.8.8/apps/emqx_schema_registry/src/emqx_schema_registry_http_api.erl),
[PostgreSQL action](https://github.com/emqx/emqx/blob/e5.8.8/apps/emqx_bridge_pgsql/src/emqx_bridge_pgsql.erl).

Grafana's current guidance recommends `grafana/grafana` for OSS images. The legacy
Compose repository is `grafana/grafana-oss`; record its installed version rather
than inferring a release from that name. This implementation supplies no automatic upgrade.
[Official image guidance](https://grafana.com/docs/grafana/latest/setup-grafana/configure-docker/).

## Prepare image archives while online

`groundStation.telemetry.imagePins` requires exactly `timescaledb`, `emqx` and
`grafana`. Each record contains `imageName` (registry repository), `imageDigest`
(`sha256:` plus 64 hex characters), and `sha256` (the verified Nix archive hash).
No production defaults are supplied. Use the inspected Linux/amd64 digest, not
a mutable tag or an ARM image from a laptop.

The shape is illustrated by
[`telemetry_nix_pins.json`](../../tests/platform/telemetry_nix_pins.json), which
contains disposable acceptance-test versions. After inspecting the real versions,
save the reviewed records separately and load them in the deployment module with
`groundStation.telemetry.imagePins = builtins.fromJSON (builtins.readFile ./telemetry-images.json);`.
Do not treat the fixture's versions as a migration decision.

The module's exact local names are `crt-ground-timescaledb`, `crt-ground-emqx`,
and `crt-ground-grafana`. Each tag is `sha256-` followed by its registry digest's
64 hex characters. The archive hash depends on this name/tag as well as the
upstream content. Using a hash computed for a different final tag will fail.

For one component, set shell variables to its inspected repository/digest/name,
then run the locked prefetcher from the repository. On this Apple-silicon Mac:

```sh
nix run .#legacyPackages.aarch64-darwin.nix-prefetch-docker -- \
  --image-name "$image_repository" --image-digest "$image_digest" \
  --os linux --arch amd64 --final-image-name "$local_image_name" \
  --final-image-tag "sha256-${image_digest#sha256:}" --json
```

Use its output `hash` as the record's `sha256`. On a Linux host, select its matching
`legacyPackages` system. Never put registry credentials into the Nix expression.
The prefetcher is an online preparation command, never part of field startup.

The enabled system exposes `config.system.build.groundTelemetryImages` with all
three archive derivations. Build and retain the entire NixOS system closure before
travel. A downloaded Docker image alone does not prepare a Nix archive, complete
offline rebuild inputs, database backup or recovery installation medium.

## Private runtime credentials

Provision one JSON file outside `/nix/store`, readable only by its owner (normally
root, mode `0600`). Its exact keys are:

| Key | Use |
| --- | --- |
| `databasePassword` | New database administrator initialization; never given to Grafana or EMQX |
| `ingestPassword` | Dedicated broker insert role |
| `readerPassword` | Dedicated Grafana read role |
| `grafanaAdminPassword` | Grafana administrator initialization |
| `emqxAdminPassword` | EMQX administrator initialization |
| `emqxApiKey` | Provisioning API key, 16-128 URL-safe characters |
| `emqxApiSecret` | Matching API secret, 16-128 URL-safe characters |
| `emqxNodeCookie` | Stable private Erlang node cookie |

All values must be nonempty strings without control characters or line breaks.
The three database passwords must differ. The database container receives all
three; Grafana receives only the reader password, and broker provisioning gives
EMQX only the ingest password. Knowing an application password does not establish
administrator access.
Passwords preserve literal dollar signs, quotes and backslashes. API key/secret
characters are limited to letters, digits, underscore and hyphen so the bootstrap
file's colon-delimited format remains unambiguous. Generate private random values
locally; do not copy disposable test credentials or commit a real example.

The root preparation unit renders private Docker environment files in
`/run/ground-telemetry` and a UID-1000-owned API bootstrap file mounted read-only
into EMQX. Only public schema/dashboard assets enter immutable packages. The
helper does not print response bodies, subprocess output or credential values.
It never puts secrets in process arguments. Docker administrators retain access
to container environments; do not grant that privilege to untrusted accounts.

An immutable HBA file requires SCRAM-SHA-256 for loopback TCP connections and
rejects other networks. Its only trusted local-socket login is `postgres`, used
by root-controlled `docker exec` for migration. The new application roles cannot
authenticate locally without their own passwords through TCP; the old data
directory's HBA file cannot silently select loopback trust.

Initialization password variables do not automatically rotate passwords already
stored in existing PostgreSQL, EMQX or Grafana data. Database provisioning does
update its dedicated `ground_ingest` and `ground_reader` roles. For deliberate
credential rotation, inventory persistent credentials, update them through the
supported product procedure, rerun preparation and restart the relevant services.
Do not treat editing the JSON file as proof that every stored password changed.

## Enable only with an inspected host configuration

Set these deployment options alongside the real hardware/network configuration:

- `groundStation.telemetry.enable = true`.
- `groundStation.telemetry.secretsFile` to the private runtime file path.
- `groundStation.telemetry.imagePins` to the three reviewed records.
- `groundStation.telemetry.stateDirectory` to persistent storage; default
  `/var/lib/ground-station/telemetry`.
- Keep `groundStation.grafana.enable = false` to avoid native/container conflicts.
- For LAN access, configure the inspected `groundStation.network.lanInterfaces`
  and reviewed external `groundStation.grafana.rootUrl`, ending in `/grafana/`.
- Enable `groundStation.operatorUi` separately for the React dashboard. Its public
  Grafana link defaults to `/grafana/` when the telemetry stack is selected.

Database, broker administration and Grafana bind to loopback. MQTT binds only to
loopback unless LAN interfaces are configured; host firewall rules then allow
1883 on those interfaces. Containers use host networking, without Docker port
publication that could bypass interface firewall rules. The migration does not
silently enable unaudited TLS, WebSocket listeners or public administration.

State is separated into `db`, `emqx/data`, `emqx/log` and `grafana`. PostgreSQL
data must match major version 17. Broker node name is fixed to `emqx@127.0.0.1`;
old EMQX state with another node identity requires its supported migration/export
procedure. Never recursively copy an uninspected running database directory.

## Startup order and status

1. Root preparation validates credentials and renders runtime files.
2. Containers load their exact local archives; no registry fallback is allowed.
3. Database provisioning waits for the final TCP server, avoiding the official
   image's temporary socket-only initialization server. It checks PostgreSQL 17,
   takes a bounded advisory lock, creates the Timescale table/index idempotently,
   applies the availability trigger and configures dedicated database roles.
4. Broker provisioning requires the migrated database and running EMQX. It checks
   Schema Registry/PostgreSQL capabilities and inventories paginated rules before
   reconciling the named schema, connector, shared action and two telemetry rules.
   Overlapping unmanaged rules block provisioning to prevent duplicate inserts.
   Unchanged owned configuration is left in place, avoiding repeated protobuf
   compilation. Masked connector passwords are reapplied to support rotation.
   Schema writes have up to 120 seconds within the provisioner's 180-second
   deadline; other API requests retain a five-second maximum.
5. Grafana starts after migration with a local datasource and dashboard. A bounded,
   recurring HTTP probe checks Grafana's storage health. It does not establish
   datasource, ingestion, physical commanding or complete station readiness.

`ground_ingest` can insert telemetry; `ground_reader` can select it and defaults
to read-only transactions. Grafana does not query as a database superuser. The
datasource keeps UID `bfk1elo58d3pca`; the dashboard keeps UID `adrc2lg` and the
existing NULL/unavailable behavior. Two exported flight velocity queries referenced
a nonexistent `timestamp` column: the packaged copy now derives seconds from
`ms_since_boot_cfc`, returning NULL across duplicate/reset timestamps. The original
manual dashboard export remains unchanged. Packaged camera panels show
unconfigured status until reviewed camera endpoints are supplied.

Useful status commands on an enabled test host:

```sh
systemctl status ground-telemetry-prepare ground-telemetry-database ground-telemetry-broker
systemctl status docker-ground-timescaledb docker-ground-emqx docker-ground-grafana
systemctl status ground-telemetry-grafana-ready.timer
journalctl -b -u ground-telemetry-database -u ground-telemetry-broker
```

Preparation and provisioning failures retry with bounded attempts. A successful
prerequisite enqueues its consumers with a nonblocking `ExecStartPost` command;
failed attempts do not request consumers that would immediately restart the
failed prerequisite. A failed prerequisite leaves consumers degraded
instead of declaring success. Service retries never send a launch, arm, wipe or
network-device power command. Closing the browser does not stop recording.

Telemetry startup is requested through `ground-telemetry.target`, which is a
background supervision target. It deliberately has no ordering behind its wanted
services. The normal OS boot target therefore does not wait forever for missing
credentials or repeatedly failing provisioning. Target activity means supervision
was requested; inspect the individual units and health checks for actual status.
The services retain their prerequisite, filesystem and shutdown dependencies.
With unchanged prerequisites, failed attempts use the configured five-second
restart delay. A successful prerequisite can request immediate consumer recovery;
explicit administrator start/restart requests can also override a pending delay.
This removes the failure feedback loop, rather than imposing a global limit on
all start requests. The Grafana probe uses `Requisite`/`After` instead
of `Requires`/`BindsTo`: it checks an already-running Grafana without starting
Grafana or its prerequisites. `PartOf` retains stop/restart propagation. See the
[systemd dependency definitions](https://www.freedesktop.org/software/systemd/man/262/systemd.unit.html)
and [success-hook ordering](https://www.freedesktop.org/software/systemd/man/262/systemd.service.html).

The overall `/readyz` deliberately remains **503**. Successful static UI serving,
Grafana process health and a running broker are separate evidence. Actual
telemetry flow, physical-command firmware and complete offline host acceptance
remain required before operational readiness can be enabled.

## Verification and remaining acceptance

Host runtime tests cover private files, literal credentials, fail-closed errors,
loopback-only HTTP/no redirects, local assets and broker reconciliation fixtures.
Nix module contracts check preload-only images, dependency/recovery ordering,
runtime-secret boundaries, persistent directories, listener/firewall scope and
the unchanged unavailable full-readiness endpoint.

From the repository on this Mac:

```sh
python3 -m unittest discover -s tests/platform
nix build .#legacyPackages.aarch64-darwin.crt.ground-telemetry -o /private/tmp/ground-telemetry-helper
nix eval --json --offline --impure --expr 'let f = builtins.getFlake (toString ./.); in import ./tests/platform/test_telemetry_module.nix { nixpkgs = f.inputs.nixpkgs.outPath; }'
```

The helper package also runs its runtime tests during the build. Its source
whitelist excludes Compose, data directories and locally added credential files.

The explicit database test creates a disposable container with no network or host
data mounts, checks Timescale/schema bootstrap twice, preserves six fixture rows,
tests unavailable NULL versus valid zero and UPDATE normalization, checks separate
role privileges, and parses all 22 packaged dashboard SQL queries. It refuses to
reuse an existing container named `ground-timescaledb` and removes only the
container it created. Use a prepared immutable image:

```sh
python3 tests/platform/telemetry_database_integration.py \
  --image timescale/timescaledb@sha256:fd4181d3c7ba4c8c7e044629a3bb446d07936da24dfe09fa8de6288c1ad7e98a
```

This digest is an isolated test fixture, not a production upgrade decision.
Full-stack integration results and remaining acceptance are recorded in the
[implementation checklist](../superpowers/plans/2026-11-09-ground-platform.md).

### Platform-specific acceptance boundary

The three Linux/amd64 module archives were prepared, hash-verified and built with
the exact local image tags. On this ARM Mac's Docker host, the EMQX Enterprise
5.8.8 amd64 image exits during `quicer_nif` initialization. The initial fixture
classifier mistook its redacted cookie-setting banner for the cause; a minimal
standalone Erlang probe identifies the native-library load failure instead.
The same-version ARM image loads that library successfully. Both probes used
network isolation with IPv6 enabled, so disabled IPv6 is not the observed cause.
This establishes a platform/image difference, not its underlying ABI cause.

The acceptance harness retains the all-amd64 manifest and separately permits
explicit per-component platform declarations for functional testing on the Mac.
A native-ARM broker test cannot establish that the amd64 image starts on the
UM560. Do not change production pins, remove a vendor component or add an
unverified runtime override just to hide this test-host failure.

On 2026-11-10, the separate mixed-platform functional test passed with EMQX
Enterprise 5.8.8 arm64, TimescaleDB 2.23.0/PostgreSQL 17 amd64, Grafana amd64
(health-reported version **13.0.2**) and an amd64 Python test client. It verified:

- Private runtime files and UID-1000 API bootstrap access.
- Distinct administrator/insert/read credentials; missing, wrong and cross-role
  passwords rejected over TCP; non-admin local-socket access rejected.
- Twice-reconciled schema/connector/action/two-rule configuration.
- Actual JSON and protobuf MQTT ingestion for seven availability/legacy cases.
- Grafana datasource authentication and anonymous Viewer dashboard access.
- Database, broker and Grafana restarts; fourteen persistent rows without duplicates.
- Network isolation, no host data binds or published ports, and complete removal
  of only the fixture's containers and volumes.

With those four exact images already prepared, rerun that scoped test on this Mac:

```sh
python3 tests/platform/telemetry_stack_integration.py \
  --images-file tests/platform/telemetry_test_images_mixed.json
```

For a suitable native x86 Linux test host, use
`tests/platform/telemetry_test_images.json` to retain the all-amd64 acceptance
attempt. Both manifests are disposable fixtures; neither selects production pins.
The actual module's amd64 archive outputs use
`tests/platform/telemetry_nix_pins.json` and can be built through
`tests/platform/test_telemetry_archives.nix`. Their hashes, canonical local tags
and Linux/amd64 image configuration were verified separately.

Current source checks passed: 17 runtime tests on both Darwin and x86 Linux helper
builds, 60 telemetry module contracts and 121 existing foundation contracts.
The platform suite ran 110 tests with one Linux-only skip. The Docker Desktop
amd64 EMQX startup failure remains recorded above. The separate full x86 NixOS VM
result below supplies service boot/recovery evidence; physical mini-PC acceptance
remains pending.

Physical UM560 installation, production pin/license inventory, backup restore,
physical cold boot/recovery with the three services, prepared maps, kiosk, wired
device telemetry and physical commanding remain separate acceptance work.

### Complete NixOS VM boot/recovery test

`tests/platform/test_telemetry_vm.nix` is an explicit manual test using the actual
NixOS profile, systemd units, static UI and all three amd64 image archives. The
guest has no NIC or host port forwarding. Test-only credentials are generated
privately inside its persistent virtual disk; no values enter the Nix store.
The four-file console normalization used by the UI VM also applies here. The
test disables Docker's unused bridge, since these containers use host networking.

The fixture withholds credentials on the first boot, then releases only that
input. It also forces the first database migration attempt to fail. The Grafana
probe timer is held out of this window so it cannot mask a missing recovery edge
by starting dependencies. Actual container SIGKILLs must produce new containers,
higher restart counts and fresh provisioning invocations. The checks then cover
synthetic ingestion, persisted rows, stable credentials, and writes after a
complete shutdown/start of the populated guest disk. The recurring probe is
tested only after those recovery cases.

On the current Apple-silicon Mac, run QEMU directly on macOS:

```sh
nix build --impure --expr 'let f = builtins.getFlake (toString ./.); pkgs = import f.inputs.nixpkgs { system = "aarch64-darwin"; }; in import ./tests/platform/test_telemetry_vm.nix { inherit pkgs; }' -o /private/tmp/ground-telemetry-vm-test --option timeout 5400 -L
```

On a native x86 Linux test host, select `x86_64-linux` for the host package set.
The guest remains x86 in either case. This test needs approximately 3 GiB guest
RAM plus host overhead and a sparse 16 GiB guest disk. Prepared archives and the
whole guest closure are build inputs; the running guest cannot fetch anything.
It is intentionally excluded from automatic branch-push image workflows.

The ARM64 Linux builder's 8 GiB host ran out of memory with both 4 GiB and 3 GiB
guests before full acceptance completed; the latter failure recorded an OOM kill.
Do not treat those partial runs as a pass or fix them by changing the service
images. The direct macOS runner avoids that particular host limit. A Linux test
host still needs enough memory and workspace for QEMU and all prepared images.

**Latest observed 2026-11-11: passed**, using the direct macOS runner, in 994 seconds,
after the retry activation change. The result is
`/nix/store/bndmzk2bzi9avmfz597gjcyx8dg4sp55-vm-test-run-ground-telemetry-offline-recovery`.
It verified degraded boot and UI availability, automatic credential/migration
recovery, real JSON/protobuf ingestion, separate database/broker/Grafana SIGKILL
recovery, and fourteen persisted rows through a complete shutdown/start on the
same disk. Credentials stayed unchanged; a new batch after boot yielded **21
correct rows without duplicates**. The recurring Grafana probe ran successfully,
all NICs remained absent, `/readyz` stayed 503 and commanding stayed disabled.

This emulated x86 guest result is separate from the earlier mixed-platform
container test. Native UM560 timing, hardware installation, Ethernet/display
behavior, abrupt whole-machine power loss and field acceptance remain unverified.

### Automatic retry scheduling regression

`tests/platform/test_telemetry_retry_vm.nix` retains the production dependency
graph but substitutes controlled failing preparation/migration/broker executables
and inert container processes. It does not test Docker images or ingestion.
Monotonic invocation timestamps must show at least 4.8 seconds between attempts
while prerequisites and failing inputs stay unchanged, with the configured
five-second restart delay. Preparation is checked with the
normal probe active; the probe is then withheld so recovery cannot depend on it.
Marker releases and container-process kills must restore the expected consumers
and fresh provisioning invocations without manually starting production units.

```sh
nix build --impure --expr 'let f = builtins.getFlake (toString ./.); pkgs = import f.inputs.nixpkgs { system = "aarch64-darwin"; }; in import ./tests/platform/test_telemetry_retry_vm.nix { inherit pkgs; }' -o /private/tmp/ground-telemetry-retry-vm --option timeout 1200 -L
```

The original graph failed with preparation attempts about 0.8–1 second apart.
On 2026-11-11 the fixed graph passed in 140 seconds: minimum observed preparation,
migration and broker gaps were 5.85, 5.93 and 5.95 seconds. The timer fired during
degraded boot without starting Grafana or executing its probe service; the probe
executed after recovery. These are emulated scheduling observations, not native
station performance measurements. See the
[retry implementation evidence](../superpowers/plans/2026-11-11-telemetry-retry-cadence.md).
