"""Supervised physical-button listener; monitoring only unless commands are allowed.

A nonce-bound all-released firmware acknowledgement is required per connection.
Legacy firmware cannot provide that proof and remains monitoring-only even when
commands are listed. Session-protocol firmware must be implemented and reviewed
before this listener can command physical hardware unattended.
Existing wire mappings are retained; in particular <X> means FRAM wipe/reboot in
this listener, despite the firmware's conflicting 'disarm' comment. Resolve that
protocol with its owner before authorizing unattended commanding.
"""
import argparse
import asyncio
import json
import logging
import os
import re
import secrets
import time

LOG = logging.getLogger("ground-command-listener")
COMMANDS = {b"<L>": "launch", b"<KA>": "fsw_key_arm", b"<X>": "fsw_wipe_fram_reboot"}


class CommandSession:
    """Bounded line parser, discarded entirely on serial disconnect."""
    def __init__(self, allowed=(), *, nonce=None):
        self.allowed = frozenset(allowed)
        if self.allowed - set(COMMANDS.values()):
            raise ValueError("unsupported command allowlist")
        if self.allowed and (not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce)):
            raise ValueError("commanding requires a new 128-bit session nonce")
        self.nonce = nonce.encode() if nonce is not None else None
        self.sequence = 0
        self.ready = False
        self.buffer = bytearray()
        self.discard = False

    def feed(self, data):
        result = []
        for byte in data:
            if byte != 10:
                if not self.discard:
                    if byte > 127 or len(self.buffer) >= 256:
                        self.buffer.clear()
                        self.discard = True
                    else:
                        self.buffer.append(byte)
                continue
            line = bytes(self.buffer).rstrip(b"\r")
            invalid = self.discard
            self.buffer.clear()
            self.discard = False
            if invalid:
                continue
            if self.nonce and line == b"READY " + self.nonce + b" btn=0 key=0 dis=0":
                self.ready = True
                continue
            parts = line.split(b" ")
            command = None
            if (self.ready and len(parts) == 4 and parts[0] == b"CMD"
                    and parts[1] == self.nonce and parts[2].isdigit() and len(parts[2]) <= 19):
                sequence = int(parts[2])
                if self.sequence < sequence <= 2**63 - 1:
                    self.sequence = sequence
                    command = COMMANDS.get(parts[3])
            if command:
                if self.ready and command in self.allowed:
                    result.append(command)
                else:
                    LOG.info("Ignored %s (not allowed)", command)
            elif line in COMMANDS:
                LOG.info("Observed legacy %s; not a fresh session command", COMMANDS[line])
        return result


def select_device(ports, serial_number, explicit=None):
    if explicit:
        return explicit
    if not serial_number:
        raise ValueError("configure --device or --serial-number; no generic Pico autodetection")
    matches = [p.device for p in ports if p.vid == 0xC0DE and p.pid == 0xCAFE
               and p.product == "LaunchButton" and p.serial_number == serial_number]
    if len(matches) != 1:
        raise ValueError("expected exactly one LaunchButton with the configured serial number")
    return matches[0]


async def send_command(uri, command):
    import websockets
    # No retry: an interrupted response cannot prove that a command did not run.
    async with websockets.connect(uri, open_timeout=5) as websocket:
        await websocket.send(json.dumps({"command": command}))
        try:
            response = await asyncio.wait_for(websocket.recv(), timeout=2)
            LOG.info("Response for %s: %s", command, response)
        except asyncio.TimeoutError:
            LOG.warning("No acknowledgement for %s; outcome unknown, not retrying", command)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--uri", default=os.environ.get("CRT_FILL_STATION_WS"))
    p.add_argument("--device", default=os.environ.get("CRT_LAUNCH_BUTTON_DEVICE"))
    p.add_argument("--serial-number", default=os.environ.get("CRT_LAUNCH_BUTTON_SERIAL"))
    p.add_argument("--allow-command", action="append", choices=sorted(COMMANDS.values()), default=[],
                   help="requires reviewed session-protocol firmware; legacy firmware never forwards")
    p.add_argument("--retry-seconds", type=float, default=2.0)
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if not args.device and not args.serial_number:
        p.error("--device or --serial-number is required")
    if args.allow_command and (not args.uri or not args.uri.startswith(("ws://", "wss://"))):
        p.error("commanding requires an explicit ws:// or wss:// --uri")
    if args.retry_seconds <= 0:
        p.error("--retry-seconds must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import serial
    import serial.tools.list_ports
    LOG.info("Starting in %s", "explicit allowlist mode" if args.allow_command else "monitor-only mode")
    while True:
        try:
            device = select_device(serial.tools.list_ports.comports(), args.serial_number, args.device)
            with serial.Serial(device, 115200, timeout=0.25, write_timeout=1) as port:
                port.reset_input_buffer()
                nonce = secrets.token_hex(16) if args.allow_command else None
                session = CommandSession(args.allow_command, nonce=nonce)
                if nonce:
                    port.write(f"SYNC {nonce}\n".encode())
                LOG.info("Connected to %s; legacy inputs are monitoring-only; awaiting nonce-bound protocol if commanding", device)
                while port.is_open:
                    data = port.read(min(port.in_waiting or 1, 256))
                    for command in session.feed(data):
                        try:
                            asyncio.run(send_command(args.uri, command))
                        except Exception:
                            LOG.exception("Command %s failed or has unknown outcome; not replaying", command)
        except KeyboardInterrupt:
            return 0
        except (serial.SerialException, OSError, ValueError):
            LOG.exception("Serial device unavailable; reconnect will require resynchronization")
            time.sleep(args.retry_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
