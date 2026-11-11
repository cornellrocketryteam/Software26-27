# Telemetry startup implementation plan

> **For agentic workers:** Use bounded workers for the NixOS integration and
> independent review; implement provisioning locally with test-first contracts.

**Goal:** Package automatic local EMQX, TimescaleDB/PostgreSQL 17 and Grafana
startup without image pulls or manual dashboard provisioning at boot.

**Architecture:** An opt-in NixOS module consumes explicitly inventoried image
digests and verified archive hashes, preloads them from the system closure, and
runs containers with `pull=never`. A packaged Python helper renders runtime-only
credentials, applies the telemetry schema/migration, and reconciles only named
broker resources through its loopback API. Grafana provisions the existing
dashboard and stable datasource from local files. Full station readiness remains
unavailable until physical commanding and the remaining acceptance gates pass.

**Tech Stack:** Locked Nixpkgs OCI containers/Docker, Python standard library,
PostgreSQL SQL, EMQX v5 management API, Grafana file provisioning, unit/module and
isolated container tests.

## Global constraints

- No changes to an existing service, data volume, device or production credential.
- Keep Compose usable until inventory, backup restore and migration acceptance.
- Missing image pins or runtime credentials prevent enablement; no guessed pins.
- Archives target Linux/amd64. Actual installed versions/edition/license need inventory.
- Bind database, broker administration and Grafana to loopback; MQTT access opens
  only on explicitly configured LAN interfaces through the host firewall.
- No network-online prerequisite, registry login, plugin download or mutating
  physical command at startup. Keep cache/build admission rules unchanged.
- Persist each service separately. Do not automatically adopt old PostgreSQL or
  EMQX directories; validate PostgreSQL major version and stable broker node name.
- Never print credentials or put them in process arguments or immutable assets.
- Keep NULL availability semantics, both telemetry topics and shared SQL action.
- UI/kiosk, Ethernet migration, physical-button firmware and hardware acceptance
  remain distinct from local telemetry startup.

## Task 1: Runtime provisioning and fixtures (parent)

Files: `ground-station/provisioning/runtime.py`,
`nix/packages/crt/ground-telemetry/package.nix`,
`tests/platform/test_telemetry_runtime.py`, and local Grafana provisioning assets.

Interface: `ground-telemetry prepare --secrets-file PATH --output PATH` writes
private Docker environment files and an EMQX API bootstrap file. Secrets JSON
keys are `databasePassword`, `ingestPassword`, `readerPassword`,
`grafanaAdminPassword`, `emqxAdminPassword`,
`emqxApiKey`, `emqxApiSecret`, `emqxNodeCookie`. `database --docker PATH --assets
PATH` applies schema/migration in container `ground-timescaledb` with a bounded
subprocess. `broker --secrets-file PATH --assets PATH --api-url URL` reconciles
schema `telemetry`, connector/action `ground_telemetry`, and rules
`ground_telemetry_json`/`ground_telemetry_protobuf` through the loopback API.

- [x] Write failing tests for missing/unsafe secrets, literal dollar/quote
  preservation, private file modes, repeated preparation and redacted failures.
- [x] Implement preparation without shell interpolation; keep credentials out of
  stdout and command arguments. Provide a JSON datasource with password lookup
  `$CRT_DATABASE_PASSWORD` and stable UID `bfk1elo58d3pca`.
- [x] Write failing database/bootstrap tests, implement bounded database startup
  and idempotent schema/migration under a session advisory lock.
- [x] Write a local HTTP fixture for create/update/retry/error cases; implement
  schema, connector, shared action and both rules in dependency order. Verify
  capabilities against official EMQX API contracts, not an assumed edition.
- [x] Build the actual helper package and exercise database semantics in an
  isolated PostgreSQL/Timescale instance; preserve valid zeros and unavailable NULL.

## Task 2: NixOS offline service graph (bounded worker)

Files: new `nix/nixos-modules/ground-station/telemetry.nix`, import in `default.nix`,
proxy integration in `ui.nix`, new `tests/platform/test_telemetry_module.nix`.

Interface: `groundStation.telemetry.enable` defaults false; `secretsFile` is a
runtime absolute path outside `/nix/store`; `stateDirectory` defaults
`/var/lib/ground-station/telemetry`; `imagePins` has exactly `timescaledb`, `emqx`,
`grafana`, each with `imageName`, `imageDigest`, `sha256`. Build archives with
`dockerTools.pullImage`, `os=linux`, `arch=amd64`, deterministic local image names.
Runtime directory is `/run/ground-telemetry`. Helper CLI is defined above.

- [x] Observe failing contracts for opt-in, missing/invalid pins, plaintext-store
  secrets, forbidden native-Grafana overlap and port/listener constraints.
- [x] Implement preload-only containers, separate persistent directories and
  bounded systemd preparation/readiness/provisioning units. Broker provisioning
  waits for database migration; browser closure never stops recording.
- [x] Proxy the container Grafana under `/grafana/`; add the public link when this
  stack is enabled. Keep `/readyz` at 503 and separate telemetry health evidence.
- [x] Evaluate actual generated container/unit configs, no network-online wait or
  pull fallback. Report build/runtime evidence separately.

## Task 3: Integration, review and runbook (parent + read-only reviewer)

Files: `docs/operations/telemetry-stack.md`, architecture/checklist, directory
READMEs and explicit/manual integration fixture under `tests/platform/`.

- [x] Run package/module/host tests and an isolated service test using prepared
  images when available; do not mistake fixture HTTP responses for vendor runtime.
- [x] Document pin capture/preparation, credentials format, backup/restore gate,
  enablement, status/failure diagnosis and edition/license/major-version checks.
- [x] Review startup/restart behavior, confidentiality and preservation of manual
  deployment. Record what is implemented versus physically unverified, then commit.

## Completion evidence and acceptance boundary

On 2026-11-10, 15 runtime tests passed on both Darwin and x86 Linux helper builds;
56 telemetry and 121 foundation module contracts passed. The host platform suite
ran 108 tests with one Linux-only skip. All three actual module archive outputs
built with verified hashes/local tags/Linux-amd64 metadata. Package source is
whitelisted to public provisioning files, excluding Compose/local credentials.

Isolated Timescale checks passed repeat setup, preservation of fixture rows,
NULL/zero/update semantics and all 22 packaged dashboard SQL queries. Independent
review identified shared admin/application passwords, implicit HBA defaults and a
quoted-FROM parsing gap; distinct credentials, immutable SCRAM HBA and an inventory
lexer closed those findings with regression checks.

The combined service test passed actual JSON/protobuf ingestion, Grafana
datasource/dashboard access, negative and cross-role authentication, service
restarts and fourteen persistent rows without duplicates. The test used a native
ARM64 EMQX 5.8.8 broker with explicitly declared mixed platforms. The amd64 EMQX
image fails QUIC NIF initialization on this ARM Mac; its cookie-setting banner
was initially misclassified. Standalone probes distinguish those conditions;
no unverified runtime workaround or production architecture change was made.

Still unchecked: native x86 broker startup, complete NixOS service cold boot and
recovery, real image/edition/license inventory, backup restore and UM560 hardware
acceptance. See the [runbook](../../operations/telemetry-stack.md). These tests
do not activate host NixOS services or establish operational readiness.
