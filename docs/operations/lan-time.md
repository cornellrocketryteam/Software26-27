# LAN time reference

The service candidate enables Chrony on the ground station and a supervised
BusyBox ntpd client on every current fill-station image. This is implemented and
module-evaluated; native daemon configuration parsing, image builds and physical
clock convergence have not yet been tested. Nothing here changes a running system
until its new generation/image is deployed.

The station serves its own clock offline (`local stratum 10`). Only board
192.168.1.106 is allowed to query; the firewall opens UDP 123 on the inspected LAN
interfaces, with remote Chrony management disabled. The board uses
`ntpd -n -p 192.168.1.206`, stays supervised and retries independently of the
application and DHCP. It does not serve time or wait for internet DNS. Changing
LAN addresses requires changing both the peer and server ACL.

Optional upstreams are set through `groundStation.timeServer.upstreamServers`;
the default is empty. Use site-approved NTP servers when WAN synchronization is
wanted. Automatic station clock steps and deprecated initstepslew are disabled:
corrections slew instead. A badly wrong RTC therefore requires deliberate clock
maintenance before operations; this configuration does not make that correction
instantaneous. No upstream or time-ready service is an application boot gate.

Offline LAN agreement is not verified UTC. NTP on this isolated LAN is not
cryptographically authenticated. The producer's kernel-sync quality flag does
not prove upstream freshness or UTC accuracy, and can remain set during a peer
outage. Keep source session/sequence and time generation as ordering evidence;
never treat wall time alone as packet order. BusyBox may step the board clock,
including after delayed initial connectivity. Producer generations detect wall
clock discontinuities without resetting the frame sequence. Existing Grafana
queries still use arrival time.

## Later acceptance (no actuation required)

Deploy the combined PC generation and matching board FIT through the normal
reviewed deployment procedure. On the mini PC, run:

```sh
systemctl is-active chronyd
sudo chronyc tracking
sudo chronyc sources -v
sudo chronyc clients
sudo ss -lunp | grep ':123'
```

With no upstreams, a local reference is expected; it is not a UTC test. Verify
that port 123 is allowed only on LAN interfaces, UDP 323 is closed and a different
client is denied by the Chrony ACL. On the board, use serial console or SSH:

```sh
ps | grep '[n]tpd'
date -u
```

Check that the single foreground process uses the configured peer. Compare time
with the station and inspect producer source time/quality/generation metadata;
`date` alone does not establish synchronization. Allow several polling cycles;
record measured skew and an acceptable operational limit before acceptance.
Reboot both systems and repeat offline. Disconnect/reconnect the board network:
application startup and local operation must remain independent, telemetry should
recover, and the same running publisher must retain its session/sequence.
Do not deliberately change the operational clock; step/backward-clock behavior
belongs in an isolated test environment. Confirm actual UTC separately when an
external reference is available.

The exact BusyBox 1.37.0 source was audited for foreground/client options and
kernel clock discipline. Chrony's local-reference behavior and clock-step
controls are documented in the [Chrony configuration manual](https://chrony-project.org/doc/4.8/chrony.conf.html).
