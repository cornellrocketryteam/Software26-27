"""Guest-only adapter for the existing synthetic telemetry assertions."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
FIXTURE = Path("/run/ground-telemetry-vm")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-source", type=Path, required=True)
    parser.add_argument("--docker", required=True)
    parser.add_argument("phase", choices=["inventory", "grafana", "publish", "rows"])
    parser.add_argument("--cycles", type=int, default=1)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("stack_acceptance", args.stack_source)
    stack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stack)
    stack.FIXTURE = FIXTURE
    try:
        if args.phase == "rows":
            columns = ("unit_id,availability_version,configured_devices_mask,valid_readings_mask,"
                       "pt_1_pressure,pt_2_pressure,load_cell,ball_valve_open,sv_1_open,ignition,qd_state")
            result = subprocess.run(
                [args.docker, "exec", "-i", "ground-timescaledb", "psql", "-X", "-U", "postgres",
                 "-d", "telemetry", "-v", "ON_ERROR_STOP=1", "-At"],
                input="SELECT row_to_json(t) FROM (SELECT " + columns
                      + " FROM telemetry_data ORDER BY pressure) t;",
                text=True, capture_output=True, timeout=30)
            stack.require(result.returncode == 0, "Cannot inspect synthetic telemetry rows.")
            actual = [list(json.loads(row).values()) for row in result.stdout.splitlines()]
            expected = [row for cycle in range(args.cycles)
                        for _, _, row in stack.synthetic_packets(cycle)]
            stack.require(actual == expected, "Telemetry rows differ after startup/recovery.")
            print(f"PASS: {len(expected)} correct synthetic rows; no duplicates.")
        else:
            stack.client_phase(args.phase, args.cycles - 1)
    except (stack.AcceptanceError, OSError, ValueError, subprocess.TimeoutExpired):
        print("VM telemetry assertion failed; private details suppressed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
