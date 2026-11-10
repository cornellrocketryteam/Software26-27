# Ground-station operator UI

React/TypeScript application built with Vite. Telemetry infrastructure, Grafana,
database migration files and the physical-button listener live in
[`../ground-station`](../ground-station/README.md). The separate Streamlit
bench client is documented in [`fill-station/client`](../fill-station/client/README.md).

## Current development workflow

```sh
cd Ground_Station_UI
npm ci
npm run dev
```

Production assets and linting:

```sh
npm run build
npm run lint
```

These are current package scripts; `vite preview` is for development inspection,
not the proposed supervised field server. `npm ci` needs a prepared package cache
or internet. Do not require it during field startup.

## Current integration boundaries

`src/App.tsx` currently contains a literal fill-station WebSocket endpoint.
The physical-command listener accepts a separately configured endpoint via
`--uri`/`CRT_FILL_STATION_WS`; the broker address also exists in
`fill-station/src/mqtt_publisher.rs`. These are not yet one deployment configuration.
Changing the UI endpoint does not configure the listener or broker.

The map has local tile support, but currently chooses remote tiles using
`navigator.onLine`. LAN connectivity alone can make this true without usable
internet. Explicit offline field mode and prepared tile coverage are required
implementation work.

## Planned network and power panel

The approved scope now includes named PoE-port controls for Omada ES205GP
switches, wireless-link health/metrics for EAP215-Bridge KIT equipment and
individual controls plus available metering for two Shelly Plug US Gen4 units.
These controls are not implemented. Device addresses, firmware, controller/API
capabilities and port/load mappings will be inventoried later; no IPs are assumed.

Use a local backend with runtime credentials, explicit operator power actions,
observed-state read-back and stale/unavailable indicators. Boot/reconnect must
never replay power commands. See the
[network/power checklist](../docs/superpowers/plans/2026-11-09-ground-platform.md#2a-add-networkpower-controls-and-bridge-metrics-to-the-operator-ui)
and [architecture](../docs/architecture/ground-platform.md#network-and-power-controls-in-the-operator-ui).

## Planned NixOS operation

Follow the [ground-platform architecture](../docs/architecture/ground-platform.md)
and [checklist](../docs/superpowers/plans/2026-11-09-ground-platform.md). The target
is a prebuilt static UI served locally, an automatically opened kiosk, provisioned
Grafana, and an independently supervised command listener. The station must boot
with WAN/laptop/fill station absent and show disconnected peers clearly.

No startup code should install packages or replay launch/arm/wipe commands. NixOS
packaging, centralized endpoint configuration, offline assets and kiosk startup
are proposed work, not features established by this README.
