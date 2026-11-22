# Combined return-to-hardware acceptance

This is the accumulating checklist for when the operator regains PC/board access.
It distinguishes software checks already completed from physical tests still
pending. The final combined update bundle and exact activation commands will be
frozen after integration; the older Grafana-restoration archive does not contain
the newly added CLI/network API. Do not reflash merely to test a source-only change.

## Software completed and checked

- Restored Commanding/Grafana were previously accepted by the operator, including
  actual commanding/recovery. Their layout is preserved in the current work.
- Flash script separates SSH/authentication failure from genuinely missing flashcp;
  bounded strict SSH and fake transfer/read-back tests passed.
- Worker/graph-pair routing, pre-build fallback and explicit platform constraints
  passed host integration tests. Compilation failure does not trigger another
  machine's compilation.
- Pending remote transfers no longer block new local builds during station outage.
  Journals/roots stay retained. Explicit `transfer-resume` and read-only status/
  dry-run are implemented; recovery creates no new release.
- Cache outbox/receipt and retention suites pass with fake stores/transports.
- Network-device registry, two-second status cache and authenticated explicit
  Shelly writes are implemented. Default candidate has no write token; Omada
  adapters and unaddressed plugs remain inactive. Host/local-HTTP and Nix contracts
  pass. No real device has been contacted by these checks.
- Manual OSPI-only CI candidate is prepared; no FlakeHub cache action or automatic
  branch-push SD builds. YAML/shell/layout checks pass; GitHub has not run it.

## One integrated maintenance session, in order

1. **Identify the baseline.** Record current/boot system paths, available disk,
   current board FIT identity and station signing public identity. Preserve one
   previous known-good boot/recovery release. Do not delete bootstrap inputs yet.
2. **Apply the frozen candidate in test mode.** Build/import with prepared inputs,
   then test-activate. Check normal SSH, displays, camera playback, fresh telemetry,
   connected Commanding and monitor fallback. No new UI design is being tested.
3. **Check the read-only network service.** After that candidate is installed:

   ```sh
   systemctl is-active ground-network-devices
   curl --fail --silent http://127.0.0.1:8080/network-api/v1/devices
   ```

   Expect seven inventory entries, Omada `inspection_pending`, plugs
   `not_configured`, and `powerWritesConfigured:false`. Verify backend port 8767
   is not directly available over LAN and existing pages remain healthy. An
   unauthenticated POST must return 403 without any device action. Do not expect
   live bridge metrics before management-interface inspection. Open the new read-only
   Network page from the station selector; verify seven cards, wiring, unknown
   versus off/zero readings and normal navigation back to Propulsion/Recovery.
4. **Enroll independent deployment SSH.** Generate the dedicated PC key and supply
   its public half for the board image. Pin verified host identity, update the FIT
   once with the reviewed enrollment image, then connect from a fresh PC session
   without a forwarded agent and after board reboot. Keep Mac recovery access.
5. **Validate the normal worker in maintenance mode.** Use the prepared validation/
   worker configurations and explicit site keys; inspect actual compiler cgroups,
   memory/task limits, free-space rejection and cleanup. Observe telemetry/cameras
   during a bounded build. Client host tests are not a substitute for this check.
6. **Exercise real publication/build/fallback.** Use a real OSPI build, signed
   publication and fresh-store Mac fetch; verify receipt/roots. Interrupt a
   transfer, inspect `scripts/platform status` and `transfer-resume --dry-run`, then
   recover with `transfer-resume` without creating another release. With station
   unavailable, verify a local build succeeds and retains pending publication.
   Reconnect and `cache-sync` without rebuilding. Record measured timings.
7. **Inspect existing Omada devices read-only.** Addresses/port wiring are already
   known. Collect hardware/firmware revisions, standalone/controller mode and
   supported local interfaces. Confirm actual PoE delivery separately from link
   connectivity, especially SK-AM64B and bridge power. Then test reviewed camera
   power controls one at a time once their adapter is implemented; do not cut an
   infrastructure uplink to test a button.
8. **Shelly enrollment, when available.** Supply each plug's address/MAC, firmware,
   component identity, authentication setting and connected load. Keep entries
   disabled until then. Test status, authorized on/off/read-back and unknown-outcome
   behavior against a suitable connected load. Missing plugs do not block the rest.
9. **Retain the accepted candidate as boot default.** Follow the guarded accepted-
   system procedure for the exact tested generation. Cold-boot PC and board without
   WAN; repeat operator/cache/network-service smoke checks. Mark runtime results
   separately from source and mocked-test results.
10. **Finish cleanup.** Remove only superseded transfer/extraction artifacts after
    checking retained release/input roots. Store GC and bootstrap-root retirement
    wait for actual offline-build/publication retention acceptance. Preserve DATA,
    telemetry history, camera credentials and private signing/SSH keys.

## Remaining software before final handoff

- Finish normal-worker/publication enrollment configuration and unified deployment
  interface; freeze the combined candidate and source/lock/manifest identities.
- The separate read-only Network page is implemented and host-tested. Verify it
  on the PC, then add reviewed power controls and actual Omada adapters after
  firmware/interface inspection. Recorded wiring is not live metrics.
- Complete reviewed archive/disk retention policy and benchmark-guided routing.
- Decide/verify CI cutover before pushing; a source edit has not changed GitHub.
- The new source-time telemetry/hybrid-test/profile-view programme is separately
  queued in `2026-11-21-telemetry-time-and-vehicle-profiles.md`; those firmware/schema
  features are not implemented by this checkpoint. Extend this acceptance sheet
  when that candidate actually includes them.

Any failure gets investigated at its first failing boundary. No need to repeat all
previous tests after an unrelated fix; repeat checks covering the changed behavior
and the final reboot/operation smoke test.

## November 22 software checkpoint

Read-only Network page and selector navigation are implemented. Twenty UI tests,
production build, targeted lint, isolated-source build and three mocked browser
suites passed. No network power writes, operator-screen redesign or deployment
occurred. Details: [Network page guide](network-device-ui.md).

## Explicit deployment CLI checkpoint

The source candidate now includes `scripts/platform deploy` (or installed
`crt-platform deploy`) with mandatory `--manifest` and `--target`. It is separate
from build/cache/transfer recovery. Once a normal accepted build returns its
manifest, use that exact path as `$manifest`:

```sh
crt-platform deploy --manifest "$manifest" --target fillstation-deploy --dry-run
crt-platform deploy --manifest "$manifest" --target fillstation-deploy
crt-platform status
```

Verify the dry-run's selected profile/target and FIT hash before the actual command.
The dedicated SSH alias/key and host pin must already be enrolled. Older raw
bootstrap/GitHub artifacts without a platform release manifest remain inputs to
the low-level flash script, not automatically fabricated release manifests.

After success, expect a separate `flash-verified` attempt, `rebootRequested:false`
and runtime acceptance pending. Confirm the build/publication manifest is unchanged.
Reboot explicitly only after the flash succeeds; verify SSH, fresh telemetry and
normal operator pages return. Do not mistake flash read-back for a successful boot.

The CLI was tested with real script/fake SSH for no-network dry-run, source hashes,
reviewed partition mapping, empty/corrupt payload rejection, independent staged
bytes, authentication failure, interrupted write without retry and installed-layout
execution outside a checkout. The script also rejects malformed MTD/capacity data.
Fifteen focused deployment/script tests and the full 136-test host workflow suite
passed. Actual native packaging/SSH enrollment/OSPI flash/boot remain pending.


## Queued optional WAN and power-station acceptance

Starlink health and EcoFlow RIVER 2 Pro monitoring/control are planned, not part
of the implemented candidate. See the November 22 optional Starlink/EcoFlow
addition in [the completion plan](../superpowers/plans/2026-11-20-ground-station-completion.md).
Later record terminal/model/firmware, EcoFlow API support and output-to-load
mapping. Compare readings with vendor displays, test WAN-loss/recovery without
interrupting local operations, and test any approved power-group controls on a
noncritical load first. Individual EcoFlow socket control/metering is unconfirmed. Research now supports
a local Starlink gRPC/MQTT path and an EcoFlow developer-cloud AC/DC-bank path;
both remain queued. EcoFlow powers physical electronics only, not either computer
or the network. Verify account/serial enrollment and actual returned fields before
enabling its adapter; see the completion plan research decision.


## Independent deployment SSH helper checkpoint

`deploy-ssh-init` now prepares a local deployment key/alias and supplied verified
host pin without contacting the board. Real local keygen and OpenSSH config-parser
tests cover repeat setup, preservation, no-agent settings, changed-pin rejection,
invalid keys and symlink refusal. Actual station key generation, public-key image
enrollment, independent SSH after reboot and board deployment are still pending.
Follow [the exact enrollment procedure](ground-station-accepted-system.md).
