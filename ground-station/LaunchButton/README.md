# Physical-command listener

The listener is now a supervised, noninteractive program. It defaults to
**monitoring only**. No WebSocket command is sent unless an explicit command
allowlist and a fresh session-protocol handshake both succeed.

`nix/packages/crt/ground-command-listener/package.nix` packages Python, pyserial,
websockets and the script; no pip install is needed at boot. Run its
`ground-command-listener --help` for configuration. Supply an inspected
`--device /dev/serial/by-id/...` or `--serial-number ...`. Serial-number selection
requires the exact LaunchButton product and VID/PID and rejects ambiguity; it
does not select an arbitrary Pico or prompt interactively. The current firmware
uses a fixed serial string, so do not assume serial numbers identify each board
uniquely without inspection.

## Firmware compatibility gate

Existing `pico_rust` firmware is **monitoring-only with the new listener**. Host
buffer clearing and a released GPIO snapshot cannot prove that messages queued
inside the firmware are fresh. The listener therefore never forwards legacy
`<L>`, `<KA>`, or `<X>` frames, even when a command is allowlisted.

The future firmware protocol supported by the host parser is:

1. After connection/reset, host generates a new random 128-bit nonce and sends
   `SYNC NONCE` followed by newline when commanding is configured.
2. Firmware must discard old queued commands, adopt that nonce, and acknowledge
   physically released inputs with `READY NONCE btn=0 key=0 dis=0` plus newline.
3. Only later physical edges may emit `CMD NONCE SEQUENCE TOKEN` plus newline.
   Sequence numbers must strictly increase, starting above zero; TOKEN is an
   explicitly reviewed wire command. Reconnect requires a new nonce/handshake.

The host rejects wrong nonces, missing handshakes, old/duplicate sequences,
unlisted commands, malformed/overlong/non-ASCII frames and buffered old messages.
It does not replay a WebSocket send after timeout: the remote result may be unknown.
Passing host parser tests does not prove the firmware or physical inputs comply.

Firmware changes and physical tests are **not implemented in this increment**.
NixOS requires both `commandPolicyReviewed` and `sessionProtocolValidated` before
nonempty `authorizedCommands`. Leave these false for current hardware.

## Existing mapping conflict requiring owner review

The old listener maps `<X>` to `fsw_wipe_fram_reboot`, while the firmware comments
call its source input disarm. `<L>` is emitted on either launch-toggle edge. These
are not resolved by automatically starting a service. Review mappings, edge
semantics, startup-held inputs and recovery with the command-button owner before
implementing/authorizing operational firmware. This change does not silently
reinterpret the wire protocol or add a new disarm command.

Host tests (no hardware, network, or Python serial dependencies required):

```sh
python3 -m unittest discover -s tests/platform -p 'test_command_listener.py'
```
