"""Local-only provisioning contracts. No configured station/device is contacted."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "ground-station/provisioning/runtime.py"
spec = importlib.util.spec_from_file_location("telemetry_runtime", SOURCE) if SOURCE.exists() else None
runtime = importlib.util.module_from_spec(spec) if spec else None
if spec:
    spec.loader.exec_module(runtime)

SECRETS = {
    "databasePassword": "literal$database'password\\value",
    "ingestPassword": "literal$ingest'password\\value",
    "readerPassword": "literal$reader'password\\value",
    "grafanaAdminPassword": "literal$grafana\"password",
    "emqxAdminPassword": "literal$emqx'password",
    "emqxApiKey": "ground_api_fixture_1234",
    "emqxApiSecret": "fixture_secret_1234567890",
    "emqxNodeCookie": "private_cookie_fixture_1234",
}


class RuntimeContracts(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime, "the packaged runtime provisioner must exist")
        self.assertEqual(runtime.SECRET_KEYS, set(SECRETS), "database roles require distinct credentials")
        self.tmp = tempfile.TemporaryDirectory(prefix="ground-telemetry-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.secret = self.root / "secrets.json"
        self.secret.write_text(json.dumps(SECRETS))
        self.secret.chmod(0o600)

    def test_preparation_preserves_literal_passwords_and_private_modes(self):
        output = self.root / "runtime"
        with patch.object(runtime.os, "chown") as chown:
            runtime.prepare(self.secret, output)
        self.assertEqual((output / "database.env").read_text(),
                         "POSTGRES_PASSWORD=" + SECRETS["databasePassword"]
                         + "\nCRT_INGEST_PASSWORD=" + SECRETS["ingestPassword"]
                         + "\nCRT_READER_PASSWORD=" + SECRETS["readerPassword"] + "\n")
        self.assertIn("CRT_DATABASE_PASSWORD=" + SECRETS["readerPassword"] + "\n",
                      (output / "grafana.env").read_text())
        self.assertNotIn(SECRETS["databasePassword"], (output / "grafana.env").read_text())
        self.assertNotIn(SECRETS["ingestPassword"], (output / "grafana.env").read_text())
        emqx = dict(line.split("=", 1) for line in (output / "emqx.env").read_text().splitlines())
        self.assertEqual(json.loads(emqx["EMQX_DASHBOARD__DEFAULT_PASSWORD"]), SECRETS["emqxAdminPassword"])
        self.assertEqual((output / "api-keys.bootstrap").read_text(),
                         SECRETS["emqxApiKey"] + ":" + SECRETS["emqxApiSecret"] + ":administrator\n")
        for name in ["database.env", "grafana.env", "emqx.env"]:
            self.assertEqual(stat.S_IMODE((output / name).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((output / "api-keys.bootstrap").stat().st_mode), 0o400)
        chown.assert_called_once_with(output / "api-keys.bootstrap", 1000, 1000)
        with patch.object(runtime.os, "chown"):
            runtime.prepare(self.secret, output)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)

    def test_unsafe_or_missing_secret_values_fail_before_writes(self):
        for bad in [{}, {**SECRETS, "databasePassword": "a\nb"},
                    {**SECRETS, "grafanaAdminPassword": ""},
                    {**SECRETS, "emqxApiKey": "inject:role"},
                    {**SECRETS, "readerPassword": SECRETS["databasePassword"]},
                    {**SECRETS, "unexpected": "not allowed"}]:
            with self.subTest(keys=list(bad)):
                self.secret.write_text(json.dumps(bad))
                with self.assertRaises(runtime.ProvisionError):
                    runtime.prepare(self.secret, self.root / "not-created")
                self.assertFalse((self.root / "not-created").exists())

    def test_secret_permissions_and_symlinks_are_rejected(self):
        self.secret.chmod(0o644)
        with self.assertRaises(runtime.ProvisionError):
            runtime.load_secrets(self.secret)
        self.secret.chmod(0o600)
        link = self.root / "alias.json"
        link.symlink_to(self.secret)
        with self.assertRaises(runtime.ProvisionError):
            runtime.load_secrets(link)

    def test_symlink_output_is_rejected(self):
        target = self.root / "target"
        target.mkdir()
        output = self.root / "runtime"
        output.symlink_to(target, target_is_directory=True)
        with self.assertRaises(runtime.ProvisionError):
            runtime.prepare(self.secret, output)
        self.assertEqual(list(target.iterdir()), [])

    def test_database_uses_bounded_stdin_and_local_container_only(self):
        calls = []
        def run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(runtime.subprocess, "run", side_effect=run):
            runtime.database("/fixture/docker", ROOT / "ground-station")
        self.assertGreaterEqual(len(calls), 2)
        self.assertIn("pg_isready", calls[0][0])
        self.assertEqual(calls[0][0][4:6], ["-h", "127.0.0.1"],
                         "readiness must ignore PostgreSQL's temporary socket-only init server")
        command, options = calls[-1]
        self.assertEqual(command[:4], ["/fixture/docker", "exec", "-i", "ground-timescaledb"])
        self.assertIn("ON_ERROR_STOP=1", command)
        self.assertIn("pg_advisory_lock", options["input"])
        self.assertIn("server_version_num", options["input"])
        self.assertIn("CREATE EXTENSION IF NOT EXISTS timescaledb", options["input"])
        self.assertIn("CREATE TABLE IF NOT EXISTS telemetry_data", options["input"])
        self.assertIn("if_not_exists => TRUE", options["input"])
        self.assertIn("normalize_fill_hardware_availability", options["input"])
        self.assertIn("GRANT INSERT ON telemetry_data TO ground_ingest", options["input"])
        self.assertIn("GRANT SELECT ON telemetry_data TO ground_reader", options["input"])
        self.assertTrue(all(call[1]["timeout"] <= 120 for call in calls))
        for value in SECRETS.values():
            self.assertNotIn(value, str(calls))

    def test_database_errors_do_not_disclose_process_output(self):
        failure = subprocess.CompletedProcess([], 1, SECRETS["databasePassword"], SECRETS["emqxApiSecret"])
        with patch.object(runtime.subprocess, "run", return_value=failure), \
             patch.object(runtime.time, "sleep"), self.assertRaises(runtime.ProvisionError) as raised:
            runtime.database("/fixture/docker", ROOT / "ground-station", attempts=1)
        self.assertNotIn(SECRETS["databasePassword"], str(raised.exception))
        self.assertNotIn(SECRETS["emqxApiSecret"], str(raised.exception))

    def test_cli_failures_are_redacted(self):
        self.secret.write_text(json.dumps({**SECRETS, "databasePassword": "private\nline"}))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = runtime.main(["prepare", "--secrets-file", str(self.secret),
                                   "--output", str(self.root / "out")])
        self.assertEqual(result, 1)
        self.assertNotIn("private\nline", err.getvalue())
        self.assertIn("Secrets contain an empty or unsupported value", err.getvalue())

    def test_local_assets_provision_stable_datasource_and_preserve_null_semantics(self):
        output = self.root / "assets"
        self.assertTrue(hasattr(runtime, "build_assets"), "local provisioning assets must be generated")
        runtime.build_assets(ROOT / "ground-station", output)
        datasource = json.loads((output / "grafana/provisioning/datasources/telemetry.yaml").read_text())["datasources"][0]
        self.assertEqual(datasource["uid"], "bfk1elo58d3pca")
        self.assertEqual(datasource["url"], "127.0.0.1:5432")
        self.assertEqual(datasource["secureJsonData"]["password"], "$CRT_DATABASE_PASSWORD")
        self.assertTrue(datasource["jsonData"]["timescaledb"])
        self.assertEqual(datasource["user"], "ground_reader")
        self.assertTrue((output / "database/pg_hba.conf").exists(), "explicit TCP authentication must be packaged")
        hba = (output / "database/pg_hba.conf").read_text()
        self.assertIn("host all all 127.0.0.1/32 scram-sha-256", hba)
        self.assertNotRegex(hba, r"(?m)^host.*trust")
        dashboard = json.loads((output / "grafana/dashboards/dashboard.json").read_text())
        panels = {panel["id"]: panel for panel in dashboard["panels"]}
        self.assertEqual(dashboard["uid"], "adrc2lg")
        self.assertIsNone(dashboard["id"])
        for panel_id in [3, 4, 5, 6]:
            self.assertEqual(panels[panel_id]["options"]["reduceOptions"]["calcs"], ["last"])
            self.assertEqual(panels[panel_id]["fieldConfig"]["defaults"]["noValue"], "Unavailable")
        self.assertNotIn("192.168.", panels[1]["options"]["content"])
        for panel_id in [23, 27]:
            query = panels[panel_id]["targets"][0]["rawSql"]
            self.assertNotIn('"timestamp"', query)
            self.assertIn("ms_since_boot_cfc", query)
            self.assertIn("1000.0", query)
        self.assertEqual((output / "proto/telemetry.proto").read_bytes(),
                         (ROOT / "ground-station/proto/telemetry.proto").read_bytes())
        for value in SECRETS.values():
            for file in output.rglob("*"):
                if file.is_file():
                    self.assertNotIn(value, file.read_text())

    def test_health_wait_uses_loopback_and_requires_healthy_database(self):
        self.assertTrue(hasattr(runtime, "wait"), "bounded local health probe must exist")
        with http_fixture() as fixture:
            runtime.wait(fixture.url + "/grafana/api/health", attempts=1)
            fixture.health = {"database": "unavailable"}
            with self.assertRaises(runtime.ProvisionError):
                runtime.wait(fixture.url + "/grafana/api/health", attempts=1)
        for url in ["http://192.0.2.1/api/health", "http://user:password@127.0.0.1/", "file:///tmp/x"]:
            with self.assertRaises(runtime.ProvisionError):
                runtime.wait(url, attempts=1)

    def test_health_redirects_never_forward_to_another_endpoint(self):
        self.assertTrue(hasattr(runtime, "wait"), "bounded local health probe must exist")
        with http_fixture() as fixture:
            fixture.redirect = True
            with self.assertRaises(runtime.ProvisionError):
                runtime.wait(fixture.url + "/grafana/api/health", attempts=1)
            self.assertEqual(fixture.requests, [("GET", "/grafana/api/health", None)])

    def test_broker_reconciles_only_owned_resources_in_dependency_order(self):
        self.assertTrue(hasattr(runtime, "broker"), "broker resource reconciler must exist")
        with http_fixture() as fixture:
            runtime.broker(self.secret, ROOT / "ground-station", fixture.url + "/api/v5", attempts=1)
            writes = [(method, path, body) for method, path, body in fixture.requests if method != "GET"]
            self.assertEqual([path for _, path, _ in writes],
                             ["/api/v5/schema_registry", "/api/v5/connectors", "/api/v5/actions",
                              "/api/v5/rules", "/api/v5/rules"])
            self.assertEqual(writes[0][2]["name"], "telemetry")
            self.assertEqual(writes[0][2]["type"], "protobuf")
            self.assertEqual(writes[1][2]["server"], "127.0.0.1:5432")
            self.assertEqual(writes[1][2]["username"], "ground_ingest")
            self.assertEqual(writes[1][2]["password"], SECRETS["ingestPassword"])
            self.assertEqual(writes[2][2]["parameters"]["sql"], (ROOT / "ground-station/emqx_action.sql").read_text())
            self.assertEqual(writes[3][2]["actions"], ["pgsql:ground_telemetry"])
            self.assertIn('"rats/raw/+"', writes[3][2]["sql"])
            self.assertIn("schema_decode('telemetry'", writes[4][2]["sql"])
            runtime.broker(self.secret, ROOT / "ground-station", fixture.url + "/api/v5", attempts=1)
            self.assertEqual(len(fixture.resources), 5)
            self.assertTrue(any(method == "PUT" for method, _, _ in fixture.requests))
            self.assertFalse(any(method == "DELETE" or "/publish" in path for method, path, _ in fixture.requests))

    def test_broker_rejects_unsupported_capability_and_redacts_server_errors(self):
        self.assertTrue(hasattr(runtime, "broker"), "broker resource reconciler must exist")
        with http_fixture() as fixture:
            fixture.unsupported = True
            with self.assertRaises(runtime.ProvisionError) as raised:
                runtime.broker(self.secret, ROOT / "ground-station", fixture.url + "/api/v5", attempts=1)
            self.assertFalse(fixture.resources)
            self.assertFalse(any("/rules" in path for _, path, _ in fixture.requests))
            for value in SECRETS.values():
                self.assertNotIn(value, str(raised.exception))

    def test_broker_cannot_report_healthy_when_connector_is_disconnected(self):
        self.assertTrue(hasattr(runtime, "broker"), "broker resource reconciler must exist")
        with http_fixture() as fixture:
            fixture.integration_status = "disconnected"
            with self.assertRaises(runtime.ProvisionError):
                runtime.broker(self.secret, ROOT / "ground-station", fixture.url + "/api/v5", attempts=1)

    def test_broker_rejects_overlapping_unmanaged_rules_before_writes(self):
        self.assertTrue(hasattr(runtime, "broker"), "broker resource reconciler must exist")
        with http_fixture() as fixture:
            fixture.resources["/api/v5/rules/manual"] = {
                "id": "manual", "enable": True, "sql": 'SELECT * FROM "rats/#"'}
            with self.assertRaises(runtime.ProvisionError):
                runtime.broker(self.secret, ROOT / "ground-station", fixture.url + "/api/v5", attempts=1)
            self.assertFalse(any(method != "GET" for method, _, _ in fixture.requests))

    def test_rule_inventory_reads_from_clause_outside_literals_and_comments(self):
        with http_fixture() as fixture:
            fixture.resources["/api/v5/rules/manual"] = {
                "id": "manual", "enable": True,
                "sql": '''SELECT 'FROM "unrelated"' AS label FROM "rats/#"'''}
            with self.assertRaises(runtime.ProvisionError):
                runtime.broker(self.secret, ROOT / "ground-station", fixture.url + "/api/v5", attempts=1)
            self.assertFalse(any(method != "GET" for method, _, _ in fixture.requests))
        with http_fixture() as fixture:
            fixture.resources["/api/v5/rules/events"] = {
                "id": "events", "enable": True,
                "sql": '''SELECT 'FROM "rats/#"' AS label /* FROM "rats/#" */ FROM "$events/client_connected"'''}
            runtime.broker(self.secret, ROOT / "ground-station", fixture.url + "/api/v5", attempts=1)


@contextlib.contextmanager
def http_fixture():
    class Fixture:
        health = {"database": "ok"}
        redirect = False
        requests = []

    fixture = Fixture()
    fixture.requests = []
    fixture.resources = {}
    fixture.unsupported = False
    fixture.integration_status = "connected"
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            fixture.requests.append(("GET", self.path, None))
            if self.path == "/api/v5/action_types":
                value = [] if fixture.unsupported else ["pgsql"]
                self.send_response(200)
            elif self.path == "/api/v5/schema_registry":
                value = []
                self.send_response(404 if fixture.unsupported else 200)
            elif self.path.startswith("/api/v5/rules?"):
                value = {"data": [body for path, body in fixture.resources.items() if "/rules/" in path],
                         "meta": {"hasnext": False}}
                self.send_response(200)
            elif self.path.startswith("/api/v5/"):
                value = fixture.resources.get(self.path)
                self.send_response(200 if value is not None else 404)
            else:
                value = fixture.health
                self.send_response(302 if fixture.redirect else 200)
            self.send_header("Content-Type", "application/json")
            if fixture.redirect:
                self.send_header("Location", fixture.url + "/unexpected")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def write_resource(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            fixture.requests.append((self.command, self.path, body))
            if fixture.unsupported:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(SECRETS["databasePassword"].encode())
                return
            if self.command == "POST":
                identifier = body.get("id") or body["name"]
                if self.path.endswith(("connectors", "actions")):
                    identifier = body["type"] + ":" + identifier
                path = self.path + "/" + identifier
            else:
                path = self.path
            value = dict(body)
            if "/connectors/" in path or "/actions/" in path:
                value["status"] = fixture.integration_status
            fixture.resources[path] = value
            self.send_response(201 if self.command == "POST" else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        do_POST = write_resource
        do_PUT = write_resource

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    fixture.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fixture
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    unittest.main()
