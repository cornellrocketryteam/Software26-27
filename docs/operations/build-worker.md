# Station build-worker setup and acceptance

The worker helper and opt-in NixOS SSH endpoint are implemented. The UM560 is
not installed or validated; station builds remain disabled. No new SD/OSPI or
dashboard test is required from the user for this host-side increment.

## Implemented behavior

- Separate `ground-builder` account with explicit keys, locked password and no
  sudo, cache-group membership or Nix trusted-user grant. It forwards Nix RPC
  through the local daemon socket, keeping builds under that daemon's limits.
- Exact forced commands: `crt-platform-builder-health-v1` and `nix-daemon --stdio`.
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

1. Complete hardware/boot inventory and initial local NixOS setup first. Back up
   existing telemetry data and preserve the operational Compose setup.
2. Validate native local builds, actual daemon CPU/RAM containment and field-mode
   behavior before setting `groundStation.builder.validated`. The initial bounds
   are one job, three cores, 300% CPU and 6 GiB RAM; measure operator latency before
   allowing heavy field workloads. Defaults continue to inhibit them.
3. For ARM emulation, prove the entire chosen graph before enabling
   `groundStation.builder.aarch64.enable` and its `validated` flag. The alternative
   x86 cross-build graph has only component evidence so far. Native x86 hardware
   alone does not make the ARM64 default graph executable.
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
Worker identity pinning is recommended and rejects mismatched/missing identities.
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
- Remote output retention during build/download: the current CLI still has an
  unrooted interval after a remote build returns and before local copying/receipt
  retention. No automatic GC is enabled, but this race must be fixed and tested
  before claiming reliable remote releases. The session lock does not solve it.
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
