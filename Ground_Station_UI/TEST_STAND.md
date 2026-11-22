# Commanding UI: restored propulsion interface

The commanding UI uses the original React/TypeScript propulsion and recovery
pages, with the familiar card grid, interaction toggle and confirmation overlays.
Automated fill and its coupled timed-vent components are removed. Manual on-rocket
SV2/MAV, key, launch and general-purpose FSW controls remain; a disconnected rocket
does not prevent local SV1/BV/QD commanding. Do not expect FSW feedback without it.

The landing page is `/`; `/propulsion` opens propulsion and `/test-stand` is a
compatibility alias. `/recovery` and `/stations` remain available. Station views
returns to the top-level monitor tabs without replacing Commanding with Grafana.

Local controls use `actuate_valve` SV1 and `bv_open`/`bv_close`. QD is the solenoid
on SV5: RELEASE sends `actuate_valve` SV5/open=true; OFF sends open=false. Neither
the displayed command state nor continuity is mechanical-position feedback.
OFF does not reconnect the QD. No stepper commands, auto pulse or auto replay.
PT1/PT2 retain the firmware's existing scaling and ADC1 CH0/CH1 mapping (0–1500 PSI
sensor range). No calibration changes are made here.

Controls start in display mode. Toggle Button Interaction State to ENABLED,
then confirm an individual request. Disconnect relocks controls and queued
requests cannot cross into a reconnected socket. No command is sent on reconnect.

## Connection configuration

The UI reads `/station-config.json`, served by nginx from the active NixOS
configuration. The bundled null endpoint is a generic safe default, not a usable
device connection. The UM560 services/cache profile now explicitly sets
`groundStation.operatorUi.fillStationWebSocketUrl = "ws://192.168.1.106:9000"`.
Grafana uses MQTT/database ingestion separately; working plots do not establish
that this WebSocket is connected. Inspect the served configuration and browser
WebSocket error before assuming a firmware or firewall fault.

## Verification

Run `npm test` and `npm run build` in Ground_Station_UI. With production preview
on 127.0.0.1:4173, run the mocked `tests/testStand.browser.py` and
`tests/operatorStartup.browser.py` via cached uv/Playwright. All sockets are
replaced and external requests blocked. These checks prove rendering and wire
messages, not device connectivity or actuation. Latest hardware acceptance must
be repeated after deploying the correction; the new Hybrid FIT need not be
reflashed solely for this UI/configuration correction.
