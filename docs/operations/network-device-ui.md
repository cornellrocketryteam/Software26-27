# Network-device status page

The source candidate includes `/network`, reached from the new Network devices
card on `/stations`. It follows the existing cream header, CRT logo and grey/white
card style. Propulsion, Recovery and Grafana layouts are preserved. The old landing
card's fill/vent description was corrected to describe manual controls.

The page is read-only. It displays the three known ES205GP switches, both bridge
ends and two unconfigured Shelly plugs. Recorded switch wiring is explicitly not
live link/PoE state. Omada metrics remain inspection-pending; no API capabilities
were invented. Shelly addresses and load mappings can be supplied later.

Only same-origin GET requests go to `/network-api/v1/devices`; the browser never
connects directly to device addresses. Polling is sequential, every three seconds
with a seven-second request deadline. It stops on navigation. Invalid response,
service failure or stale data does not turn an unknown relay into Off or missing
power into 0 W. Actual false/zero readings remain distinguishable. No credentials,
operator token entry, power requests or actuation buttons are in this page yet.

## Software verification

- 20 UI unit/contract tests and production TypeScript/Vite build passed.
- Targeted ESLint passed for the new page and response parser.
- Mocked network-page browser suite passed: seven-device inventory, port wiring,
  configured-off/zero readings, unavailable/malformed API, recovery, navigation,
  mobile layout and GET-only requests. All external requests/device sockets blocked.
- Existing Commanding and startup/Recovery browser suites passed after the addition.
- Isolated Nix-style UI source copy passed unit tests and build with only the
  explicitly packaged public fixtures. Nix evaluated the UI package recipe.
- Local desktop/mobile screenshots were visually inspected. Preview/test servers
  were stopped afterwards. No Docker, heavy Linux build or device scan was run.

## Test when back at the PC

After the combined candidate is built and test-activated (not the older update
archive), open Network devices from the station selector. Expect seven entries,
correct addresses/wiring, Omada Management inspection pending, and plugs Not
configured. Verify navigation back to Propulsion/Recovery and the existing station
monitor tabs/cameras. Check this from the attached display and a LAN browser.

Once actual plug configuration is enrolled, verify its real off/zero readings and
missing/stale readings. Interrupt only the network API during maintenance and
confirm the page marks previous readings unavailable, then recovers after restart;
operator telemetry/Commanding/Grafana must continue. Do not cut an infrastructure
PoE port to simulate a UI outage. Power controls and actual Omada adapters still
need implementation/physical acceptance; this page does not claim them ready.

The running PC has not been updated by these source/host tests. See the
[combined hardware checklist](ground-station-return-testing.md).
