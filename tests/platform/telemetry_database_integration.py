"""Explicit isolated TimescaleDB acceptance, never an existing database.

Prepare a Linux/amd64 TimescaleDB PostgreSQL-17 image first, then pass its exact
repository@sha256:digest with --image. Uses no network or host data mounts.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("runtime", ROOT / "ground-station/provisioning/runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9./_-]+@sha256:[a-f0-9]{64}", args.image):
        parser.error("--image requires an immutable repository@sha256 digest")

    def docker(*command, input=None, check=True):
        return subprocess.run([args.docker, *command], input=input, text=True,
                              capture_output=True, check=check, timeout=180)

    if docker("container", "inspect", "ground-timescaledb", check=False).returncode == 0:
        raise SystemExit("Container ground-timescaledb already exists; refusing to reuse or remove it.")
    created = None
    try:
        created = docker("run", "--detach", "--name", "ground-timescaledb", "--network", "none",
                         "--pull", "never", "--platform", "linux/amd64", "--env", "PGDATA=/pgdata",
                         "--env", "POSTGRES_PASSWORD=isolated-test-only", "--env", "POSTGRES_DB=telemetry",
                         "--env", "CRT_INGEST_PASSWORD=isolated-ingest-only",
                         "--env", "CRT_READER_PASSWORD=isolated-reader-only",
                         "--env", "TIMESCALEDB_TELEMETRY=off", args.image).stdout.strip()

        def sql(statement):
            return docker("exec", "-i", "ground-timescaledb", "psql", "-X", "-U", "postgres",
                          "-d", "telemetry", "-v", "ON_ERROR_STOP=1", "-At", input=statement).stdout.strip()

        with tempfile.TemporaryDirectory(prefix="ground-telemetry-assets-") as tmp:
            assets = Path(tmp) / "assets"
            runtime.build_assets(ROOT / "ground-station", assets)
            runtime.database(args.docker, assets)
            assert sql("SHOW server_version_num;").startswith("17")
            assert sql("SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name='telemetry_data';") == "1"
            assert docker("inspect", "--format", "{{.HostConfig.NetworkMode}}", created).stdout.strip() == "none"
            assert docker("inspect", "--format", "{{json .HostConfig.Binds}}", created).stdout.strip() in {"null", "[]"}
            columns = "time,unit_id,availability_version,configured_devices_mask,valid_readings_mask,pt_1_pressure,pt_2_pressure,load_cell,ball_valve_open,sv_1_open,ignition,qd_state"
            for unit, version, configured, valid in [(0, 0, 0, 0), (1, 1, 0, 0), (0, 1, 0, 0),
                                                     (0, 1, 4095, 7), (0, 1, 18, 2), (0, 2, 0, 0)]:
                sql(f"INSERT INTO telemetry_data({columns}) VALUES(clock_timestamp(),{unit},{version},{configured},{valid},0,0,0,false,false,false,0);")
            rows = sql("SELECT unit_id,availability_version,configured_devices_mask,valid_readings_mask,pt_1_pressure,pt_2_pressure,load_cell,ball_valve_open,sv_1_open,ignition,qd_state FROM telemetry_data ORDER BY time;").splitlines()
            assert rows == ["0|0|0|0|0|0|0|f|f|f|0", "1|1|0|0|0|0|0|f|f|f|0",
                            "0|1|0|0|||||||", "0|1|4095|7|0|0|0|f|f|f|0",
                            "0|1|18|2||0|||f|f|", "0|2|0|0|0|0|0|f|f|f|0"], rows
            runtime.database(args.docker, assets)
            assert sql("SELECT count(*) FROM telemetry_data;") == "6"
            sql("UPDATE telemetry_data SET valid_readings_mask=0 WHERE unit_id=0 AND configured_devices_mask=4095;")
            assert sql("SELECT pt_1_pressure IS NULL AND pt_2_pressure IS NULL AND load_cell IS NULL FROM telemetry_data WHERE configured_devices_mask=4095;") == "t"
            assert sql("SELECT has_table_privilege('ground_reader','telemetry_data','SELECT'), has_table_privilege('ground_reader','telemetry_data','INSERT'), has_table_privilege('ground_ingest','telemetry_data','INSERT'), has_table_privilege('ground_ingest','telemetry_data','SELECT');") == "t|f|t|f"
            assert sql("SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls FROM pg_roles WHERE rolname IN ('ground_reader','ground_ingest');").splitlines() == ["f", "f"]
            dashboard = json.loads((assets / "grafana/dashboards/dashboard.json").read_text())
            checked = 0
            for panel in dashboard["panels"]:
                for target in panel.get("targets", []):
                    if target.get("rawSql"):
                        query = target["rawSql"].replace("$__timeFilter(time)", "TRUE")
                        sql("EXPLAIN " + query)
                        checked += 1
            print(f"PASS: PostgreSQL17/Timescale bootstrap, repeat migration preserves six records, NULL/zero/update semantics, separate insert/read roles, {checked} dashboard SQL queries, no network/host bind mounts.")
    finally:
        if created:
            docker("rm", "--force", "--volumes", created)


if __name__ == "__main__":
    main()
