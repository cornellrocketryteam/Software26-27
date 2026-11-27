# EcoFlow read-only enrollment check

The optional RIVER 2 Pro integration starts with a manual developer-cloud probe.
It is packaged as `crt-probe-ecoflow`. An optional isolated background collector
and Network page card are also implemented, disabled by default. Local commanding does not depend on them. No output-control requests are
implemented. EcoFlow powers physical electronics only, never either computer or
network equipment.

Before testing, enroll the station in an EcoFlow developer account and obtain its
access key, secret key and serial. Confirm the account API region (US or EU).
Both the station and mini PC need internet for this check. Offline operation of
the rest of the ground station remains independent. Do not put developer secrets
in the repository, Nix configuration, command arguments or browser.

On the mini PC, create an owner-only file using an editor:

```sh
install -m 600 /dev/null "$HOME/ecoflow-credentials.json"
${EDITOR:-nano} "$HOME/ecoflow-credentials.json"
```

Contents, with your actual developer keys:

```json
{"accessKey":"DEVELOPER_ACCESS_KEY","secretKey":"DEVELOPER_SECRET_KEY"}
```

Preview first, then explicitly execute (substitute your serial and region):

```sh
crt-probe-ecoflow --region us --serial YOUR_SERIAL
crt-probe-ecoflow --region us --serial YOUR_SERIAL \
  --credentials-file "$HOME/ecoflow-credentials.json" --execute
```

Source-checkout equivalent: `python3 ground-station/network-devices/ecoflow_probe.py`
followed by the same arguments. The preview performs no network or credential
reads. Execution sends only an enrolled-device-list GET and, if the selected
serial is online, a quota GET. HTTPS verification is enabled, redirects and
ambient proxies are disabled, each request has a five-second socket timeout and
a one-MiB response cap. This timeout is not a hard total wall-clock deadline.
The probe prints selected metrics, not raw responses or credentials. Failure
messages deliberately omit upstream content.

Compare battery percentage and aggregate input/output watts with the EcoFlow
app under a noncritical load. `null` means absent/invalid, not zero.
`cloud-reports-offline` skips quota retrieval. `cloud-snapshot` means a cloud
response arrived: its receive time does not establish device sample freshness.
No per-socket metrics, socket control, local offline API or enrollment success
has been verified on our hardware. Model identity must be confirmed manually;
matching an enrolled serial alone does not identify its product.

If it fails, check file ownership/mode, enrollment, account region, WAN and system
clock. Do not paste keys into error reports. If this model/account cannot enroll,
leave this integration disabled. Bank controls still require separately validated
load mapping and read-back.

## Optional background monitoring after enrollment

After the manual read succeeds, install the private JSON at a persistent runtime
path, owned by root with mode 0600. Set these NixOS options in the deployment
configuration (never embed key values):

```nix
groundStation.ecoflow = {
  enable = true;
  region = "us"; # Explicitly select the account's US or EU API region.
  serial = "YOUR_SERIAL";
  credentialsFile = "/var/lib/ground-station/ecoflow.json";
  intervalSeconds = 30;
};
```

Deploy with the normal ground-station procedure. The separate `ground-ecoflow`
service receives keys through systemd LoadCredential; the Nix store and browser
never receive them. It needs DNS and outbound HTTPS; its service does not restrict
egress by vendor IP because those addresses vary. The existing LAN device
service's IP policy is unchanged. No `network-online.target` boot wait is added.
The collector has a 20-second subprocess deadline and resource limits. Reads at
`/ecoflow-api/v1/ecoflow` return only cached selected metrics, with no serial or
credentials. It is a public read-only endpoint on the existing dashboard LAN.

The card distinguishes pending, cloud-reported offline, unavailable and stale
reads. Failed reads clear metrics immediately. Cached results older than the
configured interval plus 25 seconds become stale; browser/API failures also hide
metrics. Even successful reads explicitly say device sample time is unknown.
When disabled, nginx returns a disabled JSON status without starting a collector
or making any EcoFlow requests.

Later hardware checks: compare the card with the app, disconnect WAN and confirm
metrics become unavailable, restore WAN and confirm recovery, then reboot and
verify the credential file and service persist. Confirm local telemetry,
commanding and Shelly eligibility remain independent throughout. Do not actuate
any EcoFlow output during this read-only check.

Protocol and field references (community implementation, not a vendor support guarantee):
[public API client](https://github.com/tolwi/hassio-ecoflow-cloud/blob/main/custom_components/ecoflow_cloud/api/public_api.py),
[RIVER 2 Pro fields](https://github.com/tolwi/hassio-ecoflow-cloud/blob/main/custom_components/ecoflow_cloud/devices/internal/river2_pro.py).
The [official developer portal](https://developer.ecoflow.com/us/document/introduction)
requires JavaScript; its model/account support must be checked during enrollment.
