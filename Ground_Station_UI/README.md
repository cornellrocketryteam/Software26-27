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
The physical-command listener has a separate literal endpoint in
`ground-station/LaunchButton/pc_listener.py`; the broker address also exists in
`fill-station/src/mqtt_publisher.rs`. These are not yet one deployment configuration.
Changing the UI endpoint does not configure the listener or broker.

The map has local tile support, but currently chooses remote tiles using
`navigator.onLine`. LAN connectivity alone can make this true without usable
internet. Explicit offline field mode and prepared tile coverage are required
implementation work.

## Planned NixOS operation

Follow the [ground-platform architecture](../docs/architecture/ground-platform.md)
and [checklist](../docs/superpowers/plans/2026-11-09-ground-platform.md). The target
is a prebuilt static UI served locally, an automatically opened kiosk, provisioned
Grafana, and an independently supervised command listener. The station must boot
with WAN/laptop/fill station absent and show disconnected peers clearly.

No startup code should install packages or replay launch/arm/wipe commands. NixOS
packaging, centralized endpoint configuration, offline assets and kiosk startup
are proposed work, not features established by this README.
