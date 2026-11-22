# Maintenance validation of the station Nix daemon

The `ground-station-um560-validation` profile adds a fixed administrative probe
and the installed `crt-platform` command. It is a maintenance generation:
field mode is off, but ordinary builds, remote builds and worker validation stay
off. Use the normal `ground-station-um560-services` profile for field operation.

This generation also includes the station-view navigation correction. Existing
camera credentials, telemetry state and SSD layout remain external runtime state.
Do not reinstall the station or reinitialize its secrets to apply this change.

## Build and stage

The prepared November 19 offline input bundle and exact transfer/build/test
commands are documented in [the maintenance update](ground-station-maintenance-update.md).
It builds the remaining system assembly natively on the UM560 before activation.

From the intended Git checkout, build the maintenance generation with:

```sh
scripts/platform build ground-station --profile um560-validation
```

This selects the profile; it does not deploy it. A station whose normal build
admission is disabled cannot bootstrap this generation through its normal daemon.
Prepare a complete system closure on an admitted builder, or use the documented
administrative native-build bootstrap during maintenance. Do not bypass the
admission hook globally. The earlier operations-update archive predates this
profile and must not be used as evidence that the new helper is installed.

Record the exact source revision, dirty-source snapshot and resulting system
path before transfer. Check the transferred archive and closure before activation.
Use the existing operations-update import procedure with the new system closure,
then test-activate its `bin/switch-to-configuration test` before setting the boot
default. Retain the previous accepted generation for recovery.

## Run the fixed probe

After test-activating the new maintenance generation, run on the mini PC:

```sh
sudo crt-validate-build-daemon
```

No arguments, derivation hashes, internet or private signing key are required.
The immutable package retains its probe derivation and executable inputs.
The helper rejects field mode, a field-mode marker and insufficient free space.
It contacts the real daemon socket, checks the live daemon cgroup limits, builds
a fixed recipe and forces a second execution with `--rebuild`. It checks that the
recipe used a non-root build user inside the daemon cgroup and that the limits
remained unchanged. Only this root-owned invocation clears build admission for
that fixed recipe; persistent daemon policy is unchanged.

Success prints JSON with `scope: daemon-smoke-validation`, `rebuilt: true`,
`workerValidationChanged: false`, and the observed cgroup limits. Save that output.
A failure is a failed gate: do not enable the normal or remote worker to get past it.
This is a daemon smoke check, not proof of hostile-job containment, full compiler
resource behavior, signature trust or remote-worker acceptance. Those have later
checks in the signed-cache/worker rollout plan.

Also check SSH, advancing telemetry, cameras, and both display layouts. In the
commanding page, select **Station views**, then return to Commanding; it should
remain recoverable rather than leaving both views on Grafana. Do not test valve
actuation as part of this update.

## Installed build CLI

`crt-platform` provides the checkout CLI without pip or uv setup. Build commands
must run inside the intended Git checkout (subdirectories work). It resolves the
Git root rather than treating its installed `/nix/store` package as the source.
Status and cache-sync commands can run outside a checkout. The command does not
change worker admission, and its presence does not make the station an enabled
builder.

## Current acceptance

Host Python tests and Nix module/profile evaluation cover the configuration and
probe behavior. On November 20, the operator confirmed the native build,
test activation, successful daemon probe, navigation/display/telemetry/camera
checks and persistence across reboot. The exact probe JSON was not imported into
the repository. Full remote-worker containment remains unvalidated. Signed-cache
provisioning proceeds as a separate [cache-only update](ground-station-signed-cache-update.md).
