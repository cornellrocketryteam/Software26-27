# Ground-station camera relay

This increment provides an optional native go2rtc relay and an offline standalone
viewer at `/cameras/`. It is default off. The operator confirmed all three physical camera feeds play inside Grafana on
the mini PC, including after reboot. Camera playback from the Mac is not yet
accepted: telemetry loads, but camera video fails in the reported browser.
Synthetic playback and on-station acceptance do not establish every browser's
compatibility.

## Configuration

The module is imported by the ground-station foundation and enabled in the UM560
services profile with these options:

```nix
groundStation.cameras = {
  enable = true; # default false
  credentialsFile = "/var/lib/ground-station/cameras/credentials.json";
  # apiPort = 1984; # default; loopback only, unprivileged port required
  # package = pkgs.go2rtc; # default; locked Nixpkgs version must be 1.9.15
};
```

`credentialsFile` is a string pointing to a private file already provisioned on
the station. Do not use a Nix path literal, `builtins.readFile`, `writeText`,
environment variables containing passwords, or Nix configuration containing
passwords. The module rejects store paths and traversal. The package comes from
the existing flake lock; there is no container, secondary package pin, runtime
package download, or startup fetch. A lock upgrade changing go2rtc's version
requires a transport review and an explicit module update.

The [local display](ground-station-display.md) opens Grafana with embedded cameras on
one monitor and commanding on the other; one monitor provides tabs at `/station/`. `/cameras/`
supports a same-origin iframe and a separate
browser window: responsive layout, local assets, no automatic navigation, no
parent/top navigation, and no external sources. The Dashboard link navigates
only the current browsing context. Recommended playback target is the station's
Chromium browser. Safari's HLS fallback is deliberately not exposed; Safari is
not a supported playback target for this increment.

## Fixed playback routes

| Name | Private RTSP source | Same-origin public playback |
| --- | --- | --- |
| `fillcam0` | `192.168.1.103:554/Preview_01_main` | `/cameras/fillcam0/stream.mp4` |
| `fillcam1` | `192.168.1.104:554/Preview_01_main` | `/cameras/fillcam1/stream.mp4` |
| `fillcam2` | `192.168.1.105:554/Preview_01_main` | `/cameras/fillcam2/stream.mp4` |

The username is initialized from the corresponding private camera records
(the inventory lists `admin`, matching the old cameras). Addresses and path
are new deployment intent, not physical verification. The legacy
`ground-station/go2rtc.yaml` is unchanged and is not used by this service.

The server pulls RTSP over TCP on demand and remuxes video to fragmented MP4;
audio is excluded. No transcoding runs on the station. The actual camera must
supply a codec/profile the browser supports (H.264 is the synthetic test target).
A codec mismatch requires a separately reviewed camera setting or transcoding
change; do not open more go2rtc APIs as a workaround.

Only the three exact playback locations proxy to go2rtc. They permit GET/HEAD,
clear caller arguments, omit caller headers/body, and supply a literal named
source query. Unknown paths beneath `/cameras/` return 404. There is no wildcard
API proxy, WebSocket proxy, caller-selected source, stream enumeration, config,
restart, or management route. The renderer also restricts go2rtc `allow_paths`
to `/api/stream.mp4`. API binding is `127.0.0.1:1984` by default; RTSP server and
WebRTC listeners are disabled, with empty ICE servers/candidates. No relay
firewall ports are opened. Viewer access inherits the parent station nginx
listener and network access policy. Anyone allowed to access that listener can
view the cameras; this module does not add viewer authentication.

## Provision credentials

Do not run initialization into this checkout. The helper reads the reference
file directly, resolves only its `sharedSandboxPassword` reference for each
`fill-camera-0/1/2` device, validates all inputs, and exclusively creates a mode
0600 output. It refuses to overwrite an existing file. Passwords never appear
in command arguments or successful output.

The current workstation file has already been initialized. Transfer it using the
[offline update instructions](ground-station-operations-update.md); do not rerun
initialization against that existing file. For a new workstation, initialize once:

```sh
python3 ground-station/cameras/credentials.py init \
  --reference /Users/ronit/.config/cornell-rocketry/ground-station/sandbox-network-credentials.json \
  --output /Users/ronit/.config/cornell-rocketry/ground-station/camera-relay-credentials.json
```

Transfer the resulting file through the approved private provisioning channel.
On the station, from that private staging location:

```sh
sudo install -d -m 0700 /var/lib/ground-station/cameras
sudo install -m 0600 /PRIVATE/STAGING/camera-relay-credentials.json \
  /var/lib/ground-station/cameras/credentials.json
```

`/PRIVATE/STAGING` is a placeholder for the approved runtime staging directory,
not a store path or a repository directory. The schema is exactly three keys,
`fillcam0`, `fillcam1`, `fillcam2`, each containing nonempty string `username`
and `password` fields. Do not paste the document into logs or support tickets.
After deployment the installed `ground-camera-credentials init` command provides
the same initializer without a source checkout. For rotation, securely install
the replacement runtime JSON and restart `ground-station-cameras.service`.
Existing service credentials are snapshots and do not update until restart.

## Failure and retry behavior

Systemd loads the private file with `LoadCredential`. A dynamic unprivileged
service account renders URL-escaped credentials into mode 0600 JSON (valid YAML)
under mode 0700 `/run/ground-station-cameras`, then runs native go2rtc with that
runtime config. Neither the credential document nor the rendered config is a
Nix derivation input or public asset. Root and the service necessarily have
access to these runtime secrets; loopback is not a boundary against local root.

The service restarts after failures every five seconds without rate limiting.
It orders after `network.target`, never `network-online.target`, and has no
required dependency from nginx, the dashboard, or boot. No camera is contacted
until playback is requested. Missing credentials may leave this optional service
failed/retrying, while nginx and boot remain available. An unreachable camera
causes a local playback error; the page retries each camera independently every
five seconds with a bounded initial/stall watchdog. Paused video is not a
freshness signal. The operator must verify scene motion/freshness physically.

Upstream RTSP errors may contain credentials. Therefore relay stdout/stderr are
discarded and upstream HTTP errors/redirects are replaced by a generic nginx
502 body. Do not enable debug logging, expose the private runtime YAML, or proxy
`/api/streams` for diagnostics. Public assets contain no passwords. Systemd's
unit/start/restart metadata remains available:

```sh
systemctl status ground-station-cameras.service
systemctl show ground-station-cameras.service -p ActiveState -p SubState -p NRestarts
```

If all views fail, check the private file's existence/owner/mode without printing
it, the service state, and whether another local process occupies the configured
API port. If a single view fails, later physical checks must establish power,
LAN address, credentials, RTSP path, and codec. Do not infer readiness from
`/healthz`, a loaded page, or a running relay. The browser must support the
camera codec; an autoplay block may require Play or Retry camera.

## Verification

From the repository root (no cameras or LAN device probes):

```sh
python3 -m unittest discover -s tests/platform -p test_cameras_runtime.py
nix eval --impure --json --expr 'import ./tests/platform/test_cameras.nix { nixpkgs = (builtins.getFlake (toString ./.)).inputs.nixpkgs.outPath; }'
nix build --impure --no-link --expr 'let pkgs = import (builtins.getFlake (toString ./.)).inputs.nixpkgs { system = builtins.currentSystem; }; in import ./tests/platform/test_cameras_serving.nix { inherit pkgs; }'
```

Credential and module tests were introduced before implementation and observed
failing for the missing feature. The actual generated nginx test also caught
and drove fixes for the directory index and caller-query isolation. It checks
GET/HEAD, blocked mutations, malicious query strings, hidden upstream error
bodies, unknown/API paths, and viewer/dashboard availability with the upstream
down. It uses a hostile loopback HTTP fixture, not a physical camera.

For actual relay transport, use the native locked package and an FFmpeg with
`libx264` (the workstation's existing FFmpeg is sufficient):

```sh
CAMERA_TEST_RELAY=$(nix build --impure --no-link --print-out-paths --expr 'let pkgs = import (builtins.getFlake (toString ./.)).inputs.nixpkgs { system = builtins.currentSystem; }; in pkgs.go2rtc')
GO2RTC="$CAMERA_TEST_RELAY/bin/go2rtc" python3 tests/platform/test_cameras_relay.py
```

This starts a synthetic FFmpeg pattern publisher, a separate loopback-only RTSP
source server, and the actual relay. Only in the temporary test config are the
three production sources replaced with loopback URLs. It verifies all three
fragmented MP4 streams decode, management routes are disabled, and a fresh
playback connection recovers after restarting the source without restarting the
relay. Processes and temporary files are cleaned up. The RTSP listener in this
fixture belongs to the synthetic source, not the production relay.

The relay-only checks above do not establish physical camera or monitor acceptance.
`tests/platform/grafana_camera_browser_check.py` additionally runs the pinned
Grafana image and Chrome against three synthetic streams, and checks persistent
single-screen mouse/keyboard tabs. It requires Docker and Playwright Chrome.

Camera-enabled telemetry deployments permit HTML in Grafana so the provisioned
text panel can embed the fixed same-origin `/cameras/` viewer. This setting applies
to the Grafana instance, not just that panel. Anonymous users remain Viewers and
the dashboard is file-provisioned. Camera-disabled deployments retain HTML
sanitization and the unconfigured-camera placeholder. No deployment, commit, push, legacy
credential edit, or live-device probe is part of this increment.

## Transport references

Verified against the primary tagged go2rtc 1.9.15 source:

- [MP4 HTTP handler](https://github.com/AlexxIT/go2rtc/blob/v1.9.15/internal/mp4/mp4.go): `/api/stream.mp4`, source lookup, consumer errors, and Safari HLS redirect.
- [API configuration and allow list](https://github.com/AlexxIT/go2rtc/blob/v1.9.15/internal/api/api.go): loopback binding and exact `allow_paths` registration.
- [RTSP configuration](https://github.com/AlexxIT/go2rtc/blob/v1.9.15/internal/rtsp/rtsp.go): empty listener disables the server while retaining RTSP client support; `transport=tcp` source fragment.
- [WebRTC configuration](https://github.com/AlexxIT/go2rtc/blob/v1.9.15/internal/webrtc/webrtc.go): listener and default external ICE servers, overridden here with empty settings.
- [Locked Nixpkgs native package](https://github.com/NixOS/nixpkgs/blob/6dadaf4375be35033e1c84395adbd53ff5fded96/pkgs/by-name/go/go2rtc/package.nix): go2rtc 1.9.15 source and dependency hashes. The repository's `flake.lock` remains authoritative.

## Remote Safari playback follow-up — November 19

The operator identified Safari as the failing Mac browser. The pinned go2rtc
v1.9.15 `internal/mp4/mp4.go` handler redirects Safari live MP4 requests to HLS
(`stream.m3u8`); the current fixed playback proxy replaces the User-Agent and
provides MP4 only. Thus the browser-specific fallback is unavailable. This is
the likely explanation for working Chromium playback on the station and failed
Safari playback remotely. Chrome/Edge on the same Mac remains the confirmation
check; direct `/cameras/` behavior was not yet reported.

Historical proposal (removed from active scope November 24): explicit Safari/HLS or another verified Safari-compatible playback path
with the UI work, retaining fixed camera IDs and private runtime credentials.
Do not expose go2rtc management APIs as a workaround. No camera password, board
firmware or network configuration change is indicated by the current evidence.
Primary source: https://github.com/AlexxIT/go2rtc/blob/v1.9.15/internal/mp4/mp4.go

## Remote Chrome acceptance — November 19

The operator confirmed both the standalone `/cameras/` view and camera playback
inside the full Grafana dashboard work in Chrome on the Mac. Combined with
working local Chromium playback on the mini PC, this isolates the reported
remote-viewing failure to the Safari playback path. Remote Chrome camera viewing
is accepted; Safari compatibility is excluded from the active backlog (November 24); revisit only if explicitly requested at the end. No network,
camera credential or board firmware correction was required.


## Active scope — November 24

The operator removed Safari playback work from the active backlog. Chrome /
Chromium remains the supported camera-viewing path. Earlier Safari proposals
above are historical, not queued implementation or an acceptance requirement.
