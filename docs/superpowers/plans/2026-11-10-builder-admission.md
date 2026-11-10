# Remote builder admission implementation plan

**Goal:** Add an opt-in station worker endpoint whose health reports actual runtime
readiness and whose sessions and derivation starts fail closed on field/capacity policy.

**Architecture:** A Python stdlib worker helper reads immutable Nix-generated
policy. A separate untrusted `ground-builder` SSH account admits exactly the
health command or a guarded daemon-backed Nix stdio session. A root-controlled
session lock serializes remote connections; the daemon pre-build hook independently
checks field mode/free space before every derivation. Health is advisory, not a
reservation. Existing cache ingestion and local Mac builds remain independent.

**Tech stack:** Existing Python/runtime helpers, flock, Nix daemon socket,
NixOS forced SSH commands, tmpfiles, evaluated configuration contracts and host tests.

Status: implemented and reviewed; station transport/containment acceptance pending.

## Interfaces and constraints

- Package executable: `crt-platform-worker-v1` with fixed `health`, `guard` and
  `admit` modes; no arbitrary peer command strings are interpreted.
- Common arguments: `--policy`, `--lock`, `--field-marker`, `--store-path`,
  `--binfmt-root`, and `--daemon-program`. Nix wrappers supply reviewed immutable
  paths; SSH peers cannot supply arguments.
- Policy fields: protocol 1; boolean `enabled`, `validated`, `remoteEnabled`,
  `fieldMode`; positive `minimumFreeBytes`; configured `platforms` list;
  nullable `workerId`; bounded `sessionTimeoutSeconds`.
- Health protocol 1 returns `available`, `operationalMode`, `freeBytes`,
  runtime-supported validated `platforms`, `workerId`, and a visible reason.
  Probe the daemon, native/extra platform declarations and active ARM binfmt;
  declarations alone are not execution benchmarks.
- The lock is `/run/ground-station-builder/session.lock`; its directory is root
  controlled. A guard holds it for the entire SSH stdio child lifetime. Health
  detects an occupied remote session; it cannot detect every local daemon job.
- `admit` must never ping the daemon or take the session lock: it runs inside
  the daemon's pre-build hook. It checks enabled/validated policy, field state
  and actual free bytes. Daemon cgroup limits remain on the actual build process.
- Endpoint is disabled by default, with explicit keys and worker identity required.
  The worker account is not a Nix trusted user, root or sudoer. Confirm unsigned
  input/signature behavior before claiming the full remote graph works.
- No image deployment, arming, cache publication, automatic failover after build
  errors, field-build enablement or invented hardware identities.
- Remote output retention during build/download and full transport/containment
  acceptance remain explicit unfinished work; a health response does not prove them.

## Tasks

- [x] Add failing host tests for field/disabled/unvalidated/low-space/busy states,
  daemon/capability failures, ARM binfmt and guard lifetime/timeout. Implement
  `tools/platform/worker.py` without server or board dependencies.
- [x] Package the helper; extend the NixOS builder module with opt-in forced SSH
  account, immutable policy, root-controlled lock and shared pre-build admission.
  Test defaults and invalid/valid configurations. Inspect locked Nix sources for
  untrusted daemon forwarding and signature constraints; document acceptance gaps.
- [x] Harden client health response validation and optional worker-ID pinning;
  add malformed-health and routing regression tests before changing behavior.
- [x] Run host, package and Nix checks. Review enforcement and lifecycle paths
  independently. Update docs/checklist and save a local commit when checks pass.

Review found and reproduced a killed-guard/orphan-child admission gap. The fix
inherits the lock in the proxy and installs Linux `PR_SET_PDEATHSIG` with a parent
PID race check. The Linux check `checks.aarch64-linux.ground-worker-admission`
ran all 15 worker tests successfully, without skips, using the accepted Mac Linux
builder. The corresponding x86 check is exposed but has not been run on the UM560.
Locked Nix source inspection supports the untrusted daemon-backed route and
preservation of inherited descriptors on its stdio proxy path. Actual signing,
closure import, daemon containment and station session behavior remain live tests.
The full Mac suite passed: 93 tests with one Linux-only skip, covered separately
by the 15-test Linux check above. NixOS contracts, package/wrapper smoke tests,
repository layout, whitespace and updated documentation links also passed.

Hardware tests stay pending until the mini PC is available. In particular, measure
native/emulated complete builds, verify signatures/input import, daemon containment,
field transitions and retention/copy races before enabling or preferring the worker.
