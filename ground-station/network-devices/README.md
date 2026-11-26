# Network-device adapter groundwork

This backend now includes an optional NixOS service/API. The candidate UM560 services profile enables read-only inventory; it has not been deployed. A separate read-only Network UI page is now included in source; nothing is deployed.
The accepted Commanding and Grafana layouts are untouched.

`inventory.json` records the supplied Omada addresses/wiring and two disabled
Shelly Plug US Gen4 entries. Omada adapters remain disabled until installed
firmware and the local management interface are inspected. Addresses are operator
input, not a claim that a device was contacted. No subnet scan is performed.

`shelly.py` provides a standard-library local HTTP RPC adapter:

- `ShellyDevice(config, transport=..., username=..., password=...)`
- `status()` queries Switch.GetStatus, preserving an actual false output, optional
  power/voltage/current/energy readings and missing/invalid field distinctions.
- `set_output(True/False)` sends explicit Switch.Set, then reads state back.
  A matching result confirms the device's relay report, not the attached load.
- Disabled entries make no network requests and cannot write. Configuring an
  enabled entry requires an explicit private IPv4 address and component ID.
- HTTP proxies and redirects are disabled; RPC calls have a three-second timeout
  and a bounded response body. Optional HTTP SHA-256 Digest authentication uses
  runtime credentials supplied by the caller, not this inventory.
- A failed write/read-back raises UnknownOutcome and is never retried automatically.
  Read current status before deciding to issue a new request. No automatic toggle,
  schedule, power-on default change or service-startup action is implemented.

Tests use injected replies plus an actual loopback HTTP SHA-256 challenge server:

```sh
python3 -m unittest discover -s tests/platform -p test_shelly.py
```

Actual plug firmware/model, addresses, component availability, optional metrics,
authentication and connected loads remain to be checked. No physical relay has
been commanded. The NixOS service, same-origin API and status cache are implemented. Native package/service execution, the Network page on the PC and live adapters still need acceptance. The default service has no operator token and rejects all power writes.

Sources:
- https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/Switch/
- https://shelly-api-docs.shelly.cloud/gen2/General/Authentication/

## Service/API candidate

- GET `/network-api/v1/devices` through station nginx lists public status only.
- GET `/network-api/v1/devices/<id>` reads one device; cache TTL is two seconds.
- POST `/network-api/v1/devices/<id>/output` accepts only `{"on":true/false}`,
  JSON and a runtime `Authorization: Bearer ...` operator token. No CORS access
  is provided. Missing/wrong authorization is rejected before a device call.
- The HTTP backend binds only 127.0.0.1:8767. NixOS provides a dynamic unprivileged
  user, private devices/home, resource limits and loopback/operational-LAN IP scope.
- All existing Omada entries return `inspection_pending`; all unknown-address
  plugs return `not_configured`. No adapter or power action runs for these entries.
- Status errors are unavailable/unknown with null output, never inferred off.
  The last-success timestamp remains diagnostic metadata, not a fresh reading.
- A separate optional mode-0600 runtime credentials JSON has `devices` keyed by
  inventory device ID (username/password) and an optional `operatorToken` of at
  least 24 ASCII characters. Neither credentials nor token belong in inventory,
  Git, Nix store paths or public API responses. NixOS supplies it with LoadCredential.
- `service.py --check-config` validates configuration without reading devices.
  Do not enable Omada control based on the existence of a web login page alone.

Tests: 11 API/cache/config tests (including loopback HTTP authorization checks),
9 Shelly tests, isolated-source package checks and Nix option/unit/proxy contracts.
The Nix package has not been built/run on the actual mini PC. Systemd IP-policy
support, network routes, device firmware/authentication and physical power outcomes
remain in the return-to-hardware checklist.

The source UI includes `/network` and a station-selector card. Status uses the
same-origin API with unknown/stale handling. Shelly manual controls now use the
explicit opt-in and authorization policy below; Omada remains read-only. See
`docs/operations/network-device-ui.md`.

## Manual Omada inspection

The package also installs `crt-inspect-omada`: default prints a fixed-inventory
plan; `--probe` makes read-only unauthenticated HTTP/HTTPS root checks. It neither
logs in nor enables the pending adapters or power writes. HTTPS certificate
fingerprints are unverified observations. See the ordered instructions and
firmware/metric collection list in
[`docs/operations/omada-inspection.md`](../../docs/operations/omada-inspection.md).


## Explicit per-plug control policy

Enabled Shelly adapters may read status, but `canSetOutput` and actual writes now
also require `powerControlEnabled:true` plus nonempty `connectedLoad`. Existing
configs without that flag become read-only. A runtime operator token remains
required independently. The Network page adds manual confirmation/readback
controls; both shipped entries remain disabled. See
[operator flow and physical acceptance](../../docs/operations/shelly-controls.md).
Busy-device writes return 409 without dispatch and are never queued for later
actuation. Already-dispatched requests still require readback/unknown handling.

## Optional WAN observations

The service accepts optional public --wan-config for background TCP-connect
observations. Default disabled/no targets. GET /network-api/v1/wan reads only
cached state and is separate from device reads/writes. The Network page's new
card fails independently; it does not gate local controls. These measurements
are not ICMP packet loss or Starlink terminal metrics. See
[configuration, interpretation and acceptance](../../docs/operations/wan-probes.md).
