# Operator UI packaging and local startup implementation plan

**Goal:** Build the existing React UI reproducibly and serve it on the NixOS
station without npm, internet or a fill-station connection at startup.

**Architecture:** Package locked npm dependencies and compiled assets. Load a
public, validated `/station-config.json` before opening any device socket. NixOS
generates that file from deployment options and serves the app through nginx with
SPA routing. Missing configuration gives a visible disconnected/unconfigured UI.
Keep overall `/readyz` unavailable until broker/database/Grafana/commanding are
actually provisioned. Preserve the current manual Compose stack and UI command
semantics while introducing the deployment boundary.

**Tech stack:** Existing React/TypeScript/Vite, Node tests, buildNpmPackage,
NixOS nginx, evaluated module contracts, production browser checks.

## Interfaces and constraints

- Public config schema 1: nullable `fillStationWebSocketUrl` and `grafanaUrl`,
  boolean `fieldMode`, and `map` with `tileUrl` and boolean `tilesConfigured`.
- No credentials, inferred LAN addresses or automatic mutating commands in public
  config. Default has no device endpoint and no prepared map coverage.
- Missing/invalid config fails closed, while rendering the local UI. Startup fetch
  is bounded. Do not infer internet reachability from `navigator.onLine`.
- Field-mode tiles use a local root-relative XYZ template; absent tiles remain
  visibly unavailable, with no fallback to public tile servers.
- NixOS options live under `groundStation.operatorUi`: enable (default false),
  package, fillStationWebSocketUrl, grafanaUrl, tileUrl and nullable absolute
  tilesDirectory. Field mode comes from `groundStation.fieldMode`.
- Exact `/station-config.json` serves generated JSON with no-store; asset/tile
  misses return 404, not the SPA HTML. Route refreshes serve index.html.
- Default foundation behavior remains until UI enabled. UI asset liveness is
  separate from full station readiness; no automatic commanding/arming occurs.
- Do not publish the legacy prototype's embedded Home Assistant credential.
  Remove it and leave that unused integration disabled pending a local backend.
- Broker/database/container pinning, Grafana provisioning, kiosk, map preparation,
  Ethernet migration, network/power controls and physical-button firmware remain
  separate tasks. Installed service versions/data must be inventoried for migration.

## Tasks

- [x] Add failing public-config tests, implement parsing/bounded loading, then
  wire App/bootstrap/status, explicit map configuration and bundled image assets.
- [x] Remove the embedded legacy heater credential and prevent that unused
  prototype from connecting until its local backend exists; test source absence.
- [x] Add the Nix UI package and optional nginx/public-config module behavior;
  evaluate gates/routes/defaults and build the actual static package.
- [x] Test the production UI with missing/invalid/configured local mock endpoints;
  verify only expected read/heartbeat startup traffic, offline tile behavior,
  logo assets and route refresh. No real hardware/control endpoints are contacted.
- [x] Run existing regressions and independent review; document exact supported
  commands/configuration and remaining startup/service/VM acceptance, then commit.

The existing baseline `npm run build` passed before this increment. No service
activation, database migration, device power command or physical install is part
of this change.

## Completion evidence, 2026-11-10

All 14 UI unit tests, production browser regression, 121 NixOS contracts, actual
nginx serving checks and Darwin/x86 Linux UI package builds passed. The Python
platform suite ran 93 tests with one Linux-only skip; repository layout and
relative document targets passed. Independent review findings were fixed and
retested. A manual x86 NixOS VM booted and served the UI with no network interfaces
except loopback, using software emulation on the existing ARM64 Linux builder.
The fixture normalizes four case-escaped console files for the Mac-shared store;
physical boot configuration is unchanged.

Clean npm installation required repairing Vite's lock entry from 6.4.2 to 6.4.6
within the existing ^6.4.3 range; the Nix dependency hash was verified. Existing
full-UI lint failures remain in legacy code; the new runtime-config module passes
its scoped lint check. Actual UM560 startup, prepared map coverage, kiosk and the
complete telemetry stack remain unchecked. See the current
[UI runbook](../../operations/operator-ui.md) for configuration and acceptance.
