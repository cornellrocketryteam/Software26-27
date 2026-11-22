# Station build-worker setup and acceptance

The worker helper and opt-in NixOS SSH endpoint are implemented. The UM560 now
runs the operator-confirmed NixOS/telemetry installation, but its build worker is
not validated and station builds remain disabled. The agreed normal build route
is [native x86-to-ARM cross-compilation](fill-station-cross-build.md); ARM
emulation is an optional alternative. No new SD/OSPI or
dashboard test is required from the user for this host-side increment.

## Implemented behavior

- Separate `ground-builder` account with explicit keys, locked password and no
  sudo, cache-group membership or Nix trusted-user grant. It forwards Nix RPC
  through the local daemon socket, keeping builds under that daemon's limits.
- Exact forced commands: `crt-platform-builder-health-v1`,
  `crt-platform-builder-retain-v1` and `nix-daemon --stdio`.
  Caller arguments, shell commands, forwarding and TTY are rejected.
- Immutable policy controls enabled/validated status, field mode, supported
  platforms, free-space reserve, worker identity and session deadline.
- Health checks store free bytes, daemon availability, configured native/extra
  platforms and active ARM binfmt. ARM advertisement additionally requires an
  enabled registration, fixed-interpreter flag and executable interpreter.
- A root-controlled lock serializes remote stdio sessions. The guard owns the
  lock across its child lifetime; the child inherits the lock. On Linux, parent
  death terminates the proxy; ordinary signals and deadlines terminate/reap it.
- The daemon pre-build hook independently checks enabled/validated policy,
  configured/runtime field mode and current store free space at each derivation
  start. It does not probe the daemon or acquire the remote lock from inside it.

Health is an observation, not a reservation. Another session or a field/disk
change can occur after the probe; actual admission can reject the later request.
Busy means an occupied guarded remote session, not every possible local daemon
job. The daemon still limits build concurrency and CPU/RAM. Field transitions
inhibit new derivations; they do not cancel builds already running.

The runtime field marker only adds inhibition. Removing it cannot override
configured field mode. Prepare a maintenance NixOS generation ahead of time on
a compatible builder; do not rely on compiling that transition on a station whose
current field configuration prohibits compilation.

## Configuration sequence

1. Preserve the installed NixOS services, telemetry state and recovery generation.
   Do not repeat the completed Ubuntu-to-NixOS migration.
2. Validate native local builds, actual daemon CPU/RAM containment and field-mode
   behavior before setting `groundStation.builder.validated`. The initial bounds
   are one job, three cores, 300% CPU and 6 GiB RAM; measure operator latency before
   allowing heavy field workloads. Defaults continue to inhibit them.
3. First prove complete OSPI builds with the explicit x86 cross-build graph.
   Native x86 tools still target the ARM board; this route does not require
   advertising ARM execution. Only if ARM emulation is deliberately selected,
   prove that graph before enabling `groundStation.builder.aarch64.enable` and
   its `validated` flag. Full cross-built image acceptance is still pending.
4. Provision a daemon runtime signing key and pin its public key on clients.
   This is required for input-addressed build outputs to copy back with signature
   verification. HTTP caching may remain disabled; daemon signing is separate.
5. Set `groundStation.builder.remote.authorizedKeys` to explicit bare public keys
   and `remote.workerId` to a reviewed stable nonsecret identity. Enable
   `remote.enable` only for controlled transport validation after local capability
   and containment are proven. `remote.sessionTimeoutSeconds` defaults to 14400;
   it bounds the SSH session, not each derivation.
6. Configure the inspected LAN interfaces and verify/pin the SSH host identity.
   Default listeners remain loopback, root SSH and passwords remain disabled.
7. Keep the client `station.validated` false while observing the endpoint. The
   read-only check below does not change that flag. After actual transport and
   selected-platform tests pass, record the evidence before allowing CLI routing.

Do not make the worker trusted to work around unsigned-input failures. The cache
importer is a different, explicitly privileged role. Confirm the actual graph's
source/derivation import behavior and signed result download on the station.

## Read-only check once the endpoint exists

The CLI configuration uses the dedicated account, verified known-hosts file and
matching logical worker ID. These are examples, not discovered machine values:

```json
{
  "station": {
    "validated": false,
    "platforms": ["x86_64-linux"],
    "store": "ssh-ng://ground-builder@groundstation.example.org",
    "sshTarget": "ground-builder@groundstation.example.org",
    "knownHosts": "/absolute/path/to/verified_known_hosts",
    "identityFile": "/absolute/path/to/worker_private_key",
    "workerId": "reviewed-station-worker-v1",
    "minFreeBytes": 100000000000
  }
}
```

With those real values configured:

```sh
./scripts/platform check --station --build-platform x86_64-linux
```

For the current ARM64 graph, request `aarch64-linux` instead. The check reports
local capability, the station's JSON health, the client validation flag and the
requested platform. It contacts only the fixed health command, writes no release
state, and starts no compilation. Exit zero means observation completed; inspect
`available`, platform membership, `reason` and `stationValidated`. The command
can observe a station while client routing is unvalidated or its local builder is
unavailable. Plain `./scripts/platform check` continues to make no SSH connection.

Routing still requires explicit client validation and matching platform capability.
Station builds require an explicit pinned `station.workerId`; mismatched/missing
identities and workers without retention protocol support are rejected.
There is no automatic retry of compiler failures or mid-build infrastructure errors.

## Required live tests before routine station builds

- Native execution and, if selected, ARM emulation/cross-building of both complete
  vehicle images. Record source, lock, profile, worker and output identity.
- Untrusted input/derivation import, remote build, signed output download and
  separate cache publication. Reject invalid signatures without relaxing trust.
- Field mode and runtime marker changes between probe, session start and actual
  derivation start. Existing workloads must remain bounded and visible.
- Two developer sessions, busy rejection, timeout, connection loss, forced guard
  termination and lock recovery. Test Linux parent-death behavior on Linux.
- Actual daemon cgroup membership/CPU/RAM limits under load, with measured UI and
  recording latency. Evaluated settings do not prove containment.
- Remote retention over actual untrusted SSH: disconnect before/after the
  realization reply, run station GC, reconnect, finish download, verify client
  roots, then release. Repeat with a lost release acknowledgement and simultaneous
  GC on the client. Disposable-store host tests cover import/root/GC semantics;
  actual daemon transport and signature policy still require this acceptance.
- Benchmarks against the Mac's accepted Linux builder. Leave laptop-first policy
  in place unless identical-workload measurements justify station preference.

Host tests model Nix/runtime state and exercise real process/lock/signal behavior;
the Mac run skips the Linux parent-death case. A separate Linux check ran all
15 lifecycle/policy tests in the existing ARM64 Linux builder, including that
syscall and forced-parent termination, with no skips:

```sh
nix build .#checks.aarch64-linux.ground-worker-admission
```

The same check is exposed for `x86_64-linux`. This verifies real Linux process
behavior with a modeled Nix proxy; it does not prove live station SSH, x86/ARM
image execution, actual daemon containment or board behavior.


## Bounded output-retention protocol v1

Station realization uses the exact forced command
`crt-platform-builder-retain-v1`. Stdin is one JSON object (maximum 4096 bytes,
EOF required within five seconds). No command arguments, shell fragments, store
URLs, output paths, root paths or timeouts are accepted from the peer:

```json
{
  "protocol": 1,
  "action": "realise",
  "workerId": "reviewed-station-worker-v1",
  "token": "0123456789abcdef0123456789abcdef",
  "drvPath": "/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-example.drv"
}
```

Only these five fields are accepted, with integer protocol 1, `realise` or
`release`, an exact worker identity, a 32-character lowercase hexadecimal token,
and a canonical top-level Nix derivation path. Duplicate JSON keys, booleans for
protocol, unknown fields and malformed identities/paths are rejected before
state changes. Responses echo the complete request; realization additionally
returns `retained: true` and `storePath`, while release returns `released: true`.
Clients validate protocol, action, identity, token, derivation and output path;
a successful SSH exit alone cannot authorize release or publication.

The client evaluates the frozen flake's derivation into the remote evaluation
store without realizing its result. It durably writes the token, derivation,
endpoint configuration and intended local root to `STATE/transfers/TOKEN.json`
**before** requesting realization. The worker holds the existing session lock,
checks admission, reserves a slot, then calls `nix-store --realise DRV --add-root
SLOT/root --indirect` through the daemon as the untrusted `ground-builder` user.
Nix registers the permanent root during realization while its temporary roots
protect the output (see the [Nix realization reference](https://nix.dev/manual/nix/2.24/command-ref/nix-store/realise)).
The helper verifies validity and registered-root identity
before acknowledging. It does not use build-then-root or make the account trusted.

The protocol currently accepts exactly one statically known output per
derivation. Multi-output and dynamically addressed derivations fail explicitly;
there is no fallback to the old unrooted remote build. Native local builds retain
their existing route. The daemon's pre-build hook still applies to realization.
The realization process inherits the session lock and uses the existing Linux
parent-death protection; its configured session deadline kills/reaps it.

Worker state is persistent under `/var/lib/ground-builder-retention`, owned by
`ground-builder` with mode 0700. There are at most **32 outstanding slots**, shared
across this worker account's keys. Each slot contains its immutable token/request
and one root. A duplicate token with different derivation/identity is rejected.
A matching replay returns the verified root, or retries interrupted realization.
There is no TTL, automatic pruning or eviction: disconnect cannot expire a
retained output. Exhaustion rejects new requests without removing existing roots.
This is a count bound, not a byte quota; the existing free-space admission reserve
continues to apply. Root-sized disk budgeting and per-key quotas are outside v1.
Tokens act as release capabilities among authorized users of this shared account;
there is no per-key tenant isolation.

After the acknowledgement, the client durably records the returned output. It
imports with `nix-store --realise OUTPUT --add-root LOCAL_ROOT --indirect`, using
the pinned SSH store as substituter and keeping signature requirements enabled.
On a multi-user client, its administrator must permit this URI in
`trusted-substituters` and configure the worker signing public key in
`trusted-public-keys`; this grants no worker trust and does not disable signature
checks. A rejected substituter fails the transfer and preserves the worker root.
This combines import and rooting in one Nix operation, avoiding the earlier
`nix copy` followed by rooting interval. It checks the exact local symlink,
Nix validity and registered-root mapping, then syncs the root directories before
sending `action: release` with the original token and derivation. The worker
removes only the matching slot's root. Release is idempotent, including after a
lost reply; an unknown token cannot remove another slot. The client always keeps
its local root. The server cannot inspect a remote client's filesystem: release
authorization after verified local rooting is enforced by the client protocol.

Every normal online build first replays pending transfers under a client state
lock. Offline builds leave pending transfers untouched and make no recovery SSH
connections. Dry runs perform no recovery or writes. A missing realization reply reuses the
original token. Once an output has been recorded, recovery imports/roots it and
retries release without recreating a worker reservation. Transfer state is removed
only after a validated release acknowledgement. Recovery uses the journal's
original pinned endpoint, so changing the current station configuration cannot
silently redirect an outstanding release. Compiler errors and transport failures
are surfaced; an unresolved pending transfer blocks a later online build before
new compilation. An offline local build can proceed without replaying it. Failed
realizations keep their reservation/token for recovery or operator reconciliation; they do not trigger a local compiler fallback. A recovered output
is retained locally; recovery does not invent a successful release manifest for
a build interrupted before manifest creation.

If capacity is exhausted, restore connectivity and rerun a normal build from each
client state directory with pending transfers. Preserve those journals and local
roots. A permanently lost client requires operator reconciliation of its token,
request, output and a verified replacement root before manual removal; never
bulk-delete slots to make space. Empty slot directories and temporary metadata files left before a reservation
are recoverable when no root or completed request exists. Unexpected or corrupt nonempty slot state fails closed
and needs operator inspection. Disabling the worker does not garbage-collect its
persistent roots.

Host validation commands (no station contact):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/platform -p '*retention.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/platform -p test_worker.py -v
```

The retention suite includes real process deadlines/input limits, strict wire
validation, capacity/replay/conflict handling, interrupted transfer recovery,
local-root verification before release, and GC on disposable Nix stores with an
unrooted control. It never runs GC on the system store. It does not establish
production untrusted SSH import, signed-output downloads, daemon resource
containment, or full image execution. Keep the existing live acceptance gates.
The older remote-build fixtures in `test_build_cli.py` model the superseded
unretained route and omit a pinned worker ID; they need coordinated updates to
model this protocol, rather than weakening admission to accept their old path.

## Fixed maintenance daemon check

The separate `um560-validation` profile provides a root-only fixed recipe for
checking the real daemon and cgroup without enabling the worker. See
[maintenance validation](build-daemon-validation.md) for its scope and pending
hardware acceptance. This does not replace the full remote-worker checks.

## Worker and graph selection

The build CLI now selects the worker and execution-platform graph together before
freezing/evaluating the source snapshot. For fill-station builds, an eligible
station prefers its advertised x86_64-linux graph; the local fallback tries the
existing ARM Linux route first, then native x86 when supported. Ground-station
systems always require x86_64-linux. An explicit --build-platform constrains every
candidate; --builder station never quietly falls back to local execution.

Auto defaults to local-first unless policy.preferStation is explicitly true.
--offline excludes station workers. Dry-run reports ordered routingCandidates and
their graph attributes without probing, building or changing state. This is a
planned preference, not a health assertion. Normal manifests record the actual
platform, requested platform, selected worker ID/reason and elapsed seconds before
publication. Compilation/evaluation failures after selection are not retried on
another machine. Real hardware resource validation and enrollment remain required;
these client changes do not enable or validate the running station worker.

## CI candidate cutover

The proposed `nix.yml` now has only a manual workflow_dispatch OSPI build for a
selected Hybrid/Liquid profile using native x86 Linux tools. It no longer runs
an SD image build on every branch push or uploads to FlakeHub Cache. Existing
repository-contract checks remain automatic. This is a source change, not a
claim that GitHub ran the replacement or that it has been pushed. Locked flake
inputs already use GitHub; no lock revisions were changed. The manual action is
a fallback, not the normal LAN worker/cache publication workflow.

Interrupted remote transfers are recovered only after an eligible station worker
is selected. New local builds—including auto fallback during station outage—keep
old transfer journals and roots and report recovery as deferred. A later eligible
station build retries those transfers under the existing worker-transfer lock.
Cache outbox synchronization remains independent; its failed publication never
invalidates a successfully retained new local release.

Use `scripts/platform transfer-resume --dry-run` to inspect transfer journals, or
`transfer-resume` to explicitly recover original requests/imports without creating
a new release. `status` now includes `workerTransfers`. Recovery of a realization
whose original reply was never received can resume that original work; it does
not silently substitute a new platform or create a new release. Cache publication
is still the separate `cache-sync` action, and hardware deployment stays explicit.


## Explicit connection identity

The optional `identityFile` is selected for both direct SSH and Nix store
transport. It must be an absolute, current-user-owned, nonempty regular file
with no group/other access; no symlink or SSH expansion characters are accepted.
Configured invalid files fail before transport. Explicit identity disables agent
use and forwarding; omitting the field preserves older agent/default-key setups.
Key contents are never placed in the JSON, store or journals. The local path can
appear in retained endpoint metadata; preserve it until pending transfers finish.
See [worker/publication enrollment](worker-cache-enrollment.md) for key separation,
site settings and the remaining actual-machine checks.
