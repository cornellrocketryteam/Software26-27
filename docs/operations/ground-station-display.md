# Dashboard on the mini PC's monitors

The UM560 services profile starts an unprivileged Sway/Chromium session at boot.
No laptop, typed URL or WAN connection is required. Physical GPU, monitor and
camera acceptance remains required after installing the revised update.

## Display behavior

- Two active monitors: **FillOps/Grafana with telemetry and embedded cameras** on
  one screen, and the existing **commanding/operator UI** on the other.
- One active monitor: `/station/` provides **Grafana / cameras** and **Commanding**
  tabs. Both pages stay loaded when switching. Use the mouse, Tab/Enter, or the
  arrow keys while a tab has focus. Command controls inside the UI are unchanged.
- Extra monitors receive no additional automatic views. No connected monitor
  means services continue headlessly.
- Transient compositor IPC failures preserve the browser processes and retry layout.
- Browser exits are supervised. Monitor changes are checked every two seconds;
  changing the layout restarts its browser windows.
- Grafana startup recovery restarts only Grafana/the single-screen overview,
  not the separate commanding browser.
- Cameras are embedded through the fixed local `/cameras/` viewer. There is no
  separate automatically opened camera screen or duplicate viewer column.
- `/cameras/` remains available for diagnostics. A missing camera or board does
  not prevent the pages from opening; check advancing video/telemetry separately.

Opening the commanding UI is not acceptance of actual command actuation. Existing
firmware, connection and command-policy gates remain. Browser profiles are under
`/home/operator/.config/ground-kiosk`; Chromium remains sandboxed. The operator
account has no sudo access.

## Output mapping

Names are sorted by default. To pin the two screens, use names actually reported
by Sway:

```nix
groundStation.kiosk.telemetryOutput = "HDMI-A-1";
groundStation.kiosk.commandingOutput = "DP-1";
```

These are examples, not inspected UM560 connector names. Missing outputs fall
back to the connected screens. The earlier experimental `cameraOutput` option is
replaced by `commandingOutput`. One-screen startup defaults to `/station/`.

List connected outputs from an admin console:

```sh
socket=$(printf '%s\n' /run/user/$(id -u operator)/sway-ipc.*.sock)
sudo -u operator swaymsg -s "$socket" -t get_outputs
```

After restarting the graphical service, stale socket filenames can remain. If
there is more than one, select the one whose `swaymsg` query succeeds.

## Apply and recover

Use the [prepared offline update](ground-station-operations-update.md). It updates
the existing installation without formatting the SSD. Keep telemetry state and
secrets; transfer the private camera credentials separately.

**Ctrl+Alt+F2** opens a text console for `ground-admin`. Existing SSH remains
available. To stop or restart only the display:

```sh
sudo systemctl stop greetd
sudo systemctl restart greetd
```

Inspect session failures with:

```sh
sudo journalctl -b -u greetd --no-pager -n 60
```

## Acceptance

- [x] Test-activate with two monitors: Grafana/real cameras on one, commanding on the other.
- [x] Verify advancing camera scenes and telemetry; a loaded page is insufficient.
- [ ] Check commanding page access and existing disabled/disconnected behavior without issuing actuation commands.
- [ ] Unplug one monitor: both views remain accessible through tabs; reconnect to restore separate screens.
- [ ] Verify browser/session restart, Ctrl+Alt+F2 and SSH recovery.
- [ ] After making the tested generation persistent, reboot with WAN disconnected and repeat.

Synthetic browser and VM tests establish software behavior only; physical UM560
GPU/cables, actual camera credentials/codecs and operational commands need their
separate checks.

The revised no-NIC Sway/Chromium VM passed separate Grafana/commanding placement,
single-screen fallback, hotplug, browser restart and greetd restart. The pinned
Grafana/Chrome synthetic test also passed embedded video and persistent tabs.

## Operator-confirmed display acceptance — November 18

The operator confirmed two monitors open the intended separate views directly
from boot. Turning off one display automatically moves to the two-tab view on
the remaining display. Single-monitor automatic boot, live cameras inside Grafana,
advancing fill-station telemetry and access to the commanding UI were also
confirmed. Command actuation remains untested. The navigation correction is
implemented in source but has not yet been packaged/deployed to the mini PC.
