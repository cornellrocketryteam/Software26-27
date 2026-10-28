#!/usr/bin/env bash
# Temporary test tool: run an MQTT broker on this Mac and decode the fill
# station's protobuf telemetry live. Everything comes from the repo's pinned
# nixpkgs; nothing is installed globally.
#
# Usage: tools/test-harness/mqtt-receiver/run.sh [receiver.py options]
#   e.g. run.sh --all          # print every message instead of a 1 s summary
#        MQTT_PORT=1884 run.sh # different port
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
root=$(git -C "$here" rev-parse --show-toplevel)
port=${MQTT_PORT:-1883}

nixpkgs="(builtins.getFlake \"git+file://$root\").inputs.nixpkgs.legacyPackages.\${builtins.currentSystem}"
build() {
  nix build --no-link --print-out-paths --impure --expr "let p = $nixpkgs; in $1" 2>/dev/null | tail -1
}

echo "Fetching mosquitto, protoc and Python (cached after the first run)..."
mosquitto=$(build 'p.mosquitto')
protoc=$(build 'p.protobuf')
# Full path to the interpreter: a bare `python3` lookup can start without the env's packages
python=$(build 'p.python3.withPackages (ps: [ ps.paho-mqtt ps.protobuf ])')/bin/python3

tmp=$(mktemp -d)
cleanup() {
  [[ -n ${receiver_pid:-} ]] && kill "$receiver_pid" 2>/dev/null || true
  [[ -n ${broker_pid:-} ]] && kill "$broker_pid" 2>/dev/null || true
  rm -rf "$tmp"
}
trap cleanup EXIT
trap 'exit 130' INT TERM # run cleanup (stop the broker) on Ctrl-C or kill too

# Python classes for TelemetryPayload, from the same schema the fill station uses
"$protoc/bin/protoc" -I "$root/fill-station/proto" --python_out="$tmp" telemetry.proto

cat >"$tmp/mosquitto.conf" <<EOF
listener $port 0.0.0.0
allow_anonymous true
persistence false
EOF

# Broker in the background; only connection events are shown
"$mosquitto/bin/mosquitto" -c "$tmp/mosquitto.conf" \
  > >(grep --line-buffered -E 'New client|disconnect|Error|Address already in use' | sed -u 's/^/[broker] /') 2>&1 &
broker_pid=$!
sleep 0.5
if ! kill -0 "$broker_pid" 2>/dev/null; then
  echo "Broker failed to start (is something already using port $port?)" >&2
  exit 1
fi

echo
echo "Broker listening on port $port. This Mac's addresses (BROKER_HOST must be one of these):"
ifconfig | awk '/inet / && $2 != "127.0.0.1" { print "  " $2 }'
echo "(If macOS asks whether mosquitto may accept incoming connections, allow it.)"
echo

# -u: unbuffered, so output shows up immediately even when piped to a file.
# Started in the background + `wait` so the INT/TERM trap runs right away.
PYTHONPATH="$tmp" "$python" -u "$here/receiver.py" --port "$port" "$@" &
receiver_pid=$!
wait "$receiver_pid"
