# Read-only Omada inspection

The candidate adds `crt-inspect-omada` to the existing ground-network-devices
package. It is a manual diagnostic command, not a polling/control adapter. It does
not change the Network page or enable any management API. No live Omada device
has been contacted during development.

## Run later on the mini PC

After deploying the updated PC package, as `ground-admin`:

```sh
crt-inspect-omada > "$HOME/omada-inspection-plan.json"
cat "$HOME/omada-inspection-plan.json"
crt-inspect-omada --probe > "$HOME/omada-inspection-result.json"
cat "$HOME/omada-inspection-result.json"
```

From the source checkout, the same command is:

```sh
python3 ground-station/network-devices/inspect_omada.py --probe
```

The default prints a plan without contacting anything. `--probe` contacts only
HTTP port 80 and HTTPS port 443 at the five inventory addresses:

| Device | Address |
| --- | --- |
| Ground PoE switch | 192.168.1.100 |
| Fill PoE switch 1 | 192.168.1.107 |
| Fill PoE switch 2 | 192.168.1.108 |
| Ground bridge | 192.168.1.101 |
| Fill bridge | 192.168.1.109 |

No subnet scan, DNS management alias, login, cookies, credentials, redirects,
API guessing, firmware changes, POST or power commands are used. Each endpoint
has a two-second total deadline and 16 KiB header limit, checked at each receive.
Returned fields contain HTTP status/redirect flag and optional certificate SHA256,
not response headers, login HTML, cookie values or redirect destinations. The
client stops after headers; any body bytes in the final receive are discarded.
Five devices require up to roughly twenty seconds plus local processing.

HTTPS uses certificate verification disabled solely to observe local/self-signed
management endpoints without credentials. `certificateVerified:false` and
`authenticated:false` are deliberate. A fingerprint is an observation, not proof
of device identity; independently verify it before a future authenticated adapter.
Never reuse this diagnostic TLS policy for sending passwords or control requests.

An HTTP response, even 401/403/302, confirms only a responding endpoint. A timeout
or TLS/protocol error is unavailable, not proof of a dead device or disabled PoE.
The command exits successfully when it produces a valid report even if some
endpoints are unavailable; inspect each observation. Invalid inventory exits 1
before any request. Only RFC1918 literal IPv4 addresses are accepted; no hostnames,
loopback or link-local targets. An explicit `--inventory` file can select up to
five approved entries. Disabled Omada adapters may still be manually inspected;
that flag continues to prevent automatic management/control, not this opt-in check.

## Collect the actual management evidence

For each of the three ES205GP switches and each EAP215 bridge, use your existing
browser login separately and record:

- Displayed exact model, hardware revision and installed firmware version.
- Standalone versus controller-managed mode; controller model/version if present.
- Which address/scheme actually works, including any nonstandard port.
- Whether the switch UI exposes per-port PoE state, watts, link speed and counters.
- Whether each bridge UI exposes its peer, signal/RSSI, noise/SNR, negotiated rate
  and link uptime. Record units and the UI labels; missing metrics stay unknown.

Send the JSON report and this version/metric list. Leave passwords, session
cookies, private keys, browser storage and unredacted HAR files out of the report.
The existing inventory already records port wiring; do not power-cycle any port
merely to collect this information.

## Next adapter gate

Use these exact firmware/mode results to choose a supported read interface or
controller integration. Until then all Omada API entries stay inspection-pending
and all writes stay disabled. Reachability is not radio health, PoE telemetry,
authentication validation or controller compatibility. Later camera-only power
controls need explicit output read-back and protection for bridge/uplink/board
ports; this diagnostic command does not implement those controls.

Host tests cover dry-run isolation, target validation, header limits, one deadline,
TLS fingerprint labelling, redirects/private-field exclusion and a real loopback
HTTP fixture. Packaged mini-PC execution, actual certificates, installed firmware,
management compatibility and physical metrics remain pending.
