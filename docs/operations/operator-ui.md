# Packaged operator UI and local startup

The existing React UI now has a reproducible Nix package and an optional NixOS
nginx integration. This is the first application-startup increment. It does not
provision the broker/database/Grafana stack, open a kiosk, migrate Ethernet,
enable physical-button firmware or implement network/power controls.

## Development and local inspection

From the repository:

```sh
cd Ground_Station_UI
npm ci --ignore-scripts --no-audit --no-fund
npm test
npm run build
npm run preview -- --host 127.0.0.1 --port 4173
```

Open `http://127.0.0.1:4173`. The committed configuration has no fill-station
endpoint and no prepared tiles, so it renders an explicitly unconfigured UI.
The default does not try a remembered/hard-coded board IP. `npm ci` requires
prepared dependencies or connectivity; it is a development/preparation step,
never a field startup action. Existing lint errors in context exports and legacy
explicit-any code remain; the production build/typecheck and unit tests are
separate checks. The new configuration module passes its scoped ESLint check.

The Vite lockfile was repaired within the existing `^6.4.3` manifest range to
locked `6.4.6`; the prior `6.4.2` entry could not satisfy a clean offline npm install.

On the current Apple-silicon Mac, build the self-contained assets with:

```sh
nix build .#legacyPackages.aarch64-darwin.crt.ground-operator-ui -o /private/tmp/ground-operator-ui
```

The corresponding Linux attribute is
`legacyPackages.x86_64-linux.crt.ground-operator-ui`. Nix fetches dependency
archives by the verified lockfile hash during preparation; the resulting output
contains static assets, not `node_modules` or a Vite development server. Building
does not activate a service or connect to a device. This is not a guarantee that
arbitrary uncached source can build offline.

## Public runtime configuration

The browser loads `/station-config.json` with no caching and a three-second
deadline before opening a device socket. Missing/invalid configuration renders a
visible error and uses the disconnected defaults. Public fields are:

```json
{
  "schemaVersion": 1,
  "fillStationWebSocketUrl": null,
  "grafanaUrl": null,
  "fieldMode": true,
  "map": {
    "tileUrl": "/tiles/{z}/{x}/{y}.png",
    "tilesConfigured": false
  }
}
```

During Vite development/preview, that file is `public/station-config.json`
(`dist/station-config.json` after building). Supply an inspected endpoint explicitly
when connection testing is appropriate; do not commit guessed device addresses.
Runtime configuration is public: no passwords, tokens or URL credentials belong
in it. WebSocket addresses require `ws://`/`wss://` without fragments or embedded
credentials. Grafana accepts a safe root-relative or HTTP(S) URL.

An established WebSocket means transport connectivity, not operational readiness.
Startup requests hardware availability and sends the existing heartbeat. This
increment does not authorize automatic launch/arm/power actions or replace the
existing page-level command policy. Constructor failures, connection loss and
unconfigured endpoints remain visibly distinguishable.

Map selection no longer uses `navigator.onLine`. In field mode the XYZ template
must be local/root-relative. `tilesConfigured` means a source is configured, not
that every geographic tile exists. Unprepared maps show unavailable. Missing
tiles leave the map/markers mounted with a visible message and retry button; a
new target area can load its own coverage. There is no public-server fallback.
Prepare actual tile coverage separately before field acceptance.

The unused legacy heater prototype's embedded Home Assistant token was removed,
and that prototype stays disabled pending a local credentials backend. Its owner
must revoke/rotate the previously committed token before using that integration.
No Home Assistant/device service was contacted or reconfigured by this change.

## NixOS startup integration

After the actual hardware/network inventory, opt in using
`groundStation.operatorUi.enable = true`. Options also include `package`,
`fillStationWebSocketUrl`, `grafanaUrl`, `tileUrl` and `tilesDirectory`.
`fieldMode` comes from `groundStation.fieldMode`. The default remains off, keeping
the existing foundation landing page until this integration is selected.

NixOS serves generated configuration at the exact `/station-config.json` route,
overriding the bundled development default, with JSON MIME type and `no-store`.
The UI is served through nginx at the configured station web port. Route refreshes
use the SPA index; missing `/assets/` or `/tiles/` files return 404, not HTML.
Optional prepared tile files are served from an explicitly configured absolute
`tilesDirectory`, readable by nginx. No tile downloads or directory population
occur at startup. Missing device configuration does not block nginx/UI startup.

The existing interface/firewall rules remain scoped to inspected Ethernet LAN
interfaces; defaults listen only on loopback. No service is activated by building
the asset package. Kiosk/display startup remains a separate pending task.

Health meanings remain separate:

| Endpoint | Meaning |
| --- | --- |
| `/healthz` | Foundation HTTP service is alive |
| `/ui-healthz` | UI index assets can be served; enabled with the UI module |
| `/readyz` | Still 503: complete telemetry/commanding stack is not provisioned |

Native Grafana, if separately enabled/configured, defaults the public UI link to
`/grafana/`. A link or process-health check does not provision its datasource or
dashboard. Preserve the current Compose deployment until migration/restore and
startup acceptance pass.

## Verification and remaining acceptance

Unit tests cover schema/URLs, fail-closed config loading and legacy credential
absence. The production browser regression uses mocked sockets and blocks native
WebSockets/non-local HTTP; it checks disconnected/configured startup, socket
failure/reconnect, image assets, route refresh and local-map failure/recovery.
Actual nginx tests use the module-generated configuration for routing, JSON cache
headers, tile aliases and liveness/readiness separation.

On 2026-11-10, all 14 UI unit tests, the production browser regression, all 121
NixOS module contracts, nginx serving checks and Darwin/x86 Linux UI package
builds passed. The Python platform suite ran 93 tests with one Linux-only skip.
Independent review closed the WebSocket-fragment and map-retry findings.

The manual VM check is `tests/platform/test_operator_ui_vm.nix`, using a Linux
host and an x86 guest with software emulation. It is not added to branch-push CI.
The guest has no network interfaces other than loopback; the test driver uses
its serial backdoor. This checks local HTTP startup without WAN or a board peer.
It does not run a browser inside the guest or start the telemetry stack.
The Mac-shared store case-escapes colliding ncurses directory names; the fixture
copies four console files into collision-free paths for initrd assembly. This
test-only normalization does not change physical boot configuration. The
network-free VM test passed on 2026-11-10: nginx/UI routes and generated settings
were available, missing assets returned 404 and full `/readyz` remained 503.
This result is separate from browser checks and actual UM560 installation.

From the repository on a prepared Linux builder host:

```sh
nix build --impure --expr 'let flake = builtins.getFlake (toString ./.); pkgs = import flake.inputs.nixpkgs { system = builtins.currentSystem; }; in import ./tests/platform/test_operator_ui_vm.nix { inherit pkgs; }' -o /tmp/ground-operator-ui-vm-test
```

The current Apple-silicon workstation instead selected `aarch64-linux` explicitly
and delegated to its existing Linux builder. The x86 guest uses software
emulation; this does not establish UM560 timing or physical boot compatibility.

Still required: actual Ethernet configuration and device endpoint testing, a
complete telemetry stack with pinned/preloaded images, migration/restore and
Grafana provisioning, kiosk startup, map coverage, physical controls and offline
cold-boot acceptance on the mini PC.
