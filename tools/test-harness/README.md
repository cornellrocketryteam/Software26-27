# Fill-station test harness (temporary)

Two tools for bench-testing the fill station without the real flight computer or ground
station. Delete this whole directory once testing is done (`git rm -r tools/test-harness`).

## 1. `fsw-sim-pico/`: flight computer simulator (Pico 2)

Acts as the FSW on the umbilical: USB serial with the FSW's USB IDs (`c0de:cafe`),
`$TELEM` lines at 20 Hz in the exact 54-field format from `UMBILICAL_REFERENCE.md`, and
responses to the fill station's commands (`<S>`/`<s>`, `<M>`/`<m>`, `<V>`, `<L>`, `<KA>`, ...).
SV2 and MAV state in its telemetry follow the commands it receives. Lines starting with
`SIM:` are its log output; the fill station only logs those at debug level, which release
builds compile out, so to see them plug the Pico into your Mac and open the serial port
(`screen /dev/cu.usbmodem* 115200`).

Build and flash (needs `PICO_SDK_PATH`, which points at `~/pico-sdk` on this Mac):

```bash
cd tools/test-harness/fsw-sim-pico
cmake -S . -B build && cmake --build build -j
# Hold BOOTSEL while plugging in the Pico 2, then:
cp build/fsw_sim.uf2 /Volumes/RP2350/
```

Plug it into the SK-AM64B's USB host port; it appears as `/dev/ttyACM0`.

- **LED:** solid = streaming; slow blink = no host has the port open; fast blink = paused.
- **BOOTSEL button:** pause/resume `$TELEM` while USB stays up (simulates a hung FSW).
  The fill station should mark the umbilical stale after 3 s and run its umbilical safety
  action (close ball valve, open SV1) after 15 s.
- **Unplug the cable** to test a real disconnect.
- `<R>` makes it reboot (USB drops and comes back), like the real FSW.

## 2. `mqtt-receiver/`: MQTT broker + decoder on this Mac

```bash
tools/test-harness/mqtt-receiver/run.sh          # 1 s summaries
tools/test-harness/mqtt-receiver/run.sh --all    # every message
```

Starts mosquitto on port 1883 and decodes `rats/pb/0` with the same `telemetry.proto` the
fill station uses. It prints this Mac's IP addresses at startup. The fill station's broker
address is compiled in (`BROKER_HOST` in `fill-station/src/mqtt_publisher.rs`), so it must
match this Mac's IP **on the network the board is on**; rebuild the image after changing it.
macOS may ask to allow incoming connections for mosquitto; allow it. Ctrl-C stops everything.

Each summary line shows the fill station's own values (`fill:`) and the FSW values
relayed from the umbilical (`fsw:`, or "no FSW data" when the umbilical is down).

## Test checklist

- [ ] Receiver shows ~10 msg/s from the fill station with `fill:` values updating
- [ ] With the Pico plugged in: `fsw:` shows mode, SV2, MAV, `cfc_t` counting up
- [ ] SV2 / MAV commands from the dashboard flip SV2 / MAV in `fsw:`
- [ ] BOOTSEL pause: `fsw:` goes to "no FSW data" after ~3 s; umbilical safety fires after 15 s
- [ ] Unplug / replug the Pico: umbilical drops and recovers
- [ ] Stop the receiver for a bit, restart it: the fill station reconnects to the broker on its own
