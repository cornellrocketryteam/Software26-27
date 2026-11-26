# Optional WAN TCP probes

The candidate adds a read-only WAN-probe card to Network devices. It reports
connections to explicitly configured external TCP endpoints. It does not identify
Starlink hardware, query the terminal, measure radio signal, perform speed tests,
or measure ICMP packet loss. Default collection is disabled with no targets and
no public probe traffic.

## Configuration after choosing targets

In the selected mini-PC NixOS site configuration, for example:

```nix
groundStation.networkDevices.wan = {
  enable = true;
  intervalSeconds = 10;
  timeoutMilliseconds = 1000;
  targets = [
    { label = "Approved external service"; address = "1.1.1.1"; port = 443; }
  ];
};
```

This is an example, not an enabled setting or a claim that the endpoint is always
available. Choose one to three approved public unicast IPv4 addresses/ports.
Hostnames, loopback, private/link-local and reserved/multicast targets are refused;
no DNS lookup, discovery or target fallback is used. Duplicate endpoint pairs are
refused. Interval is 5–300 seconds and timeout is 100–3000 ms per target. Public
address policy is also validated by the runtime. Invalid configuration fails
validation/startup rather than silently substituting other targets.

The service gains only the selected target /32 entries in its existing systemd
IP policy when enabled. It needs no raw-socket capability, no terminal credentials
and no network-online boot dependency. The standalone service accepts equivalent
public JSON via --wan-config; --check-config validates without starting probes.
No deployed site configuration is enabled by this source change.

## What the card means

- **At least one TCP connection succeeded:** one configured connection completed
  in the last completed round. It is not proof that every Internet service works.
- **No TCP connections succeeded:** all configured attempts failed. This includes
  refused ports, firewall/policy errors and timeouts; a refusal can come from a
  responding host. It is not proof the router, bridge or Starlink terminal is dead.
- **Last TCP connect:** elapsed monotonic time for the last successful connection
  in that target's current round. Failed/stale/pending observations show no timing.
  This is TCP setup timing, not ping RTT, throughput or application response time.
- **Recent probe failures:** failed attempts / attempts, over at most 30 rounds per
  target. Optional API failureFraction and meanSuccessfulConnectMs describe that
  bounded history; successful timings alone enter the mean. No failure count is
  labelled packet loss.
- **Observed consecutive failed-round span:** elapsed time from the first to last
  completed all-target-failed rounds in the current run of observations. The first
  failure has span zero. A successful round resets it. It cannot establish the
  beginning or full duration of an outage, especially at startup.
- **Stale:** no completed round within interval + total configured probe timeouts
  + five seconds. Current timings/reachability and failure span become unavailable,
  while recent counters remain historical diagnostics. Monitor restart clears the
  in-memory window; no persistent outage history is added.

Targets are probed sequentially outside the monitor lock. Each round completes
before the interval wait, so the actual cadence is interval plus probe work. Earlier
targets in a round can be older than its completion timestamp by the remaining
probe work. This is sampled connectivity evidence, not continuous link state.
checkedUnixMs is the PC clock's timestamp, not verified UTC; age uses monotonic time.

## Local operation and API isolation

A separate background thread collects only when enabled. GET /network-api/v1/wan
returns its cached snapshot and never performs probes on demand. The existing
device-status/control endpoint remains separate. No response from these external
targets is needed for startup, fill-station telemetry, commanding, cameras or local
Shelly control.

The card polls the local cached endpoint every five seconds with a two-second
deadline. WAN-probe failure, a stale snapshot or unavailable WAN API changes only
this card; it does not clear local-control authorization or replay commands. Missing
WAN endpoints on older PC images display monitoring unavailable. The card has no
power, router, terminal reboot/stow or recovery actions.

## Later acceptance

1. With default collection disabled, confirm Monitoring not configured and the
   existing inventory/control pages behave normally. No public probe targets
   should be contacted.
2. Choose targets and test-activate the explicit configuration. Validate the
   generated settings and service IP permissions; compare TCP connections/timing
   with reference checks against those same targets.
3. Disconnect WAN during an approved setup, leaving the LAN powered. Check failed
   probe rounds while telemetry, commanding, cameras and local Shelly state
   continue. WAN/API recovery must not replay any control request.
4. Stop only the probe collector/API in a disposable fixture to check stale and
   unavailable display. Do not cut infrastructure PoE merely to simulate an outage.
5. Identify Starlink terminal/router model and local interface later. Vendor
   obstruction, terminal uptime/history, radio/terminal-specific diagnostics and
   actual packet-loss measurements remain separate unfinished work.

Host evidence: injected time/probe tests, actual loopback TCP timing, deterministic
refusal, cached API checks, no-probe-on-check-config, UI parser/build/lint,
Nix permission/default/startup contracts and mocked browser WAN/Shelly-independence
checks. No public target or Starlink terminal was probed, no power request was
performed, and actual mini-PC deployment/systemd policy/routes remain untested.
