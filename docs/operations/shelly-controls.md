# Manual Shelly controls on Network devices

The candidate adds explicit **Turn on / Turn off** requests to existing Shelly
cards on `/network`, preserving the page's style and all Commanding/Grafana views.
Both real plug entries remain disabled, without addresses or load assignments.
No real relay was contacted or commanded during implementation.

## Configuration gate

An installed plug needs its verified private IPv4 address/component ID and
`enabled:true` for status. Power control additionally requires
`powerControlEnabled:true` and a nonempty `connectedLoad` describing the verified
physical load. The backend independently enforces this gate, not only the browser.
Omitting the new flag defaults to read-only, including previously enabled plugs.
The service must also have its private runtime `operatorToken` configured; normal
inventory/status never returns that token or device credentials.

Example inventory fields after physical identification (not enrolled by this work):

```json
{"id":"shelly-plug-1","kind":"shelly","model":"Shelly Plug US Gen4",
 "enabled":true,"address":"192.168.1.120","componentId":0,
 "connectedLoad":"REPLACE WITH VERIFIED LOAD","powerControlEnabled":true}
```

The example address is illustrative, not the unknown real plug address. Do not
turn on control before replacing both placeholders and verifying which equipment
is connected. Keep networking/computers on their intended independent power path.
No Omada port controls or management adapter is enabled by this UI change.

## Operator flow

1. Open Network devices and inspect the plug/load/address and fresh relay reading.
2. Enter the runtime operator token in the password field. It exists only in that
   component's memory: no local/session storage, URL, application log or default
   credential. The server checks authorization on every power request; entering
   text does not prove it is valid.
3. Choose Turn on/off. The button for the reported current state is disabled.
   Review the confirmation showing the exact plug ID, load and address, then
   confirm or cancel. No request is sent before confirmation.
4. Wait for explicit relay readback and the next fresh status. Relay state does
   not prove the attached load is operating. There is no optimistic relay update,
   toggle command, scheduled action or automatic retry/replay.
5. Lock controls or leave/reload the page to clear its token. Status/network errors,
   authorization rejection, invalid/mismatched readback or unknown outcomes also
   lock controls as appropriate. Never resend merely because an outcome is unknown:
   inspect fresh device status and the physical load first.

The browser sends only same-origin `/network-api/...` calls; it never opens a
socket to a plug. POST uses JSON `{ "on": true/false }`, bearer authorization,
no browser credentials and redirect rejection. Its deadline is eight seconds.
Aborting/navigating away cannot undo a relay request already received by the
server, so inspect status after returning. Unknown outcome is not assumed Off.

Buttons stay disabled for unconfigured writes, missing mapping/address,
unavailable/stale/unknown relay state, missing token or an in-flight request.
Confirmation rechecks current eligibility and exact load/address before sending.
A status reply started before a write cannot restore pre-write readings. Polling
pauses during writes, then fresh status must arrive before controls are eligible
again. Clearing an unavailable service does not replay a previous request.
The backend rejects a busy device immediately with HTTP 409 and no power
dispatch, rather than queueing a write behind reads or another write. The UI
reports that refusal and waits for fresh status before a new confirmation.

## Later hardware acceptance

After the combined candidate is test-activated, verify both unknown-address
entries remain Not configured and all power buttons disabled. With each actual
plug identified, configure status first and compare relay/watts/voltage readings.
Then explicitly enable control only for a ready, approved test load, provision
runtime authorization and test on/off, cancellation and relay readback. Compare
physical load behavior separately. Check wrong-token rejection, disconnected
plug/API, unknown output, restart/reload locking and recovery without replay.
Keep Commanding, video and network connectivity functioning throughout.

Host verification includes UI parser/policy tests, production TS/Vite build,
targeted lint, backend/injected and loopback authorization/readback tests, and
mocked browser confirmation/cancel, unknown-outcome locking, stale status,
pre-write polling races and changed-load cancellation. No physical power,
installed plug firmware, actual private credentials or PC deployment is validated.
