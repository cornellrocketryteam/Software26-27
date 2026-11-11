"""Bounded, local telemetry provisioning; never operates physical devices."""
import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


class ProvisionError(Exception):
    """Safe diagnostic; response bodies and credentials must never be included."""


SECRET_KEYS = {
    "databasePassword", "ingestPassword", "readerPassword", "grafanaAdminPassword", "emqxAdminPassword",
    "emqxApiKey", "emqxApiSecret", "emqxNodeCookie",
}


def load_secrets(path):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            metadata = os.fstat(stream.fileno())
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077
                    or metadata.st_uid not in {0, os.geteuid()}):
                raise ProvisionError("Secrets must be an owner-only regular file.")
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ProvisionError("Secrets file exceeds its size limit.")
        values = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        raise ProvisionError("Cannot read a valid private secrets file.") from None
    if not isinstance(values, dict) or set(values) != SECRET_KEYS:
        raise ProvisionError("Secrets file has an unsupported shape.")
    for value in values.values():
        if (not isinstance(value, str) or not 1 <= len(value) <= 4096
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ProvisionError("Secrets contain an empty or unsupported value.")
    for key in ("emqxApiKey", "emqxApiSecret"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", values[key]):
            raise ProvisionError("API credentials must use 16-128 URL-safe characters.")
    if len({values[key] for key in ("databasePassword", "ingestPassword", "readerPassword")}) != 3:
        raise ProvisionError("Database administrator, ingest and reader passwords must differ.")
    return values


def _write_private(path, content, mode=0o600, owner=None):
    fd, temporary = tempfile.mkstemp(prefix=".credential-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if owner is not None:
            os.chown(path, *owner)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare(secrets_file, output):
    values = load_secrets(secrets_file)
    output = Path(output)
    if output.is_symlink() or (output.exists() and (
            not output.is_dir() or output.stat().st_uid != os.geteuid())):
        raise ProvisionError("Runtime output must be an owned directory, not a symlink.")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    _write_private(output / "database.env", "POSTGRES_PASSWORD=" + values["databasePassword"]
                   + "\nCRT_INGEST_PASSWORD=" + values["ingestPassword"]
                   + "\nCRT_READER_PASSWORD=" + values["readerPassword"] + "\n")
    _write_private(output / "grafana.env",
                   "GF_SECURITY_ADMIN_PASSWORD=" + values["grafanaAdminPassword"]
                   + "\nCRT_DATABASE_PASSWORD=" + values["readerPassword"] + "\n")
    _write_private(output / "emqx.env",
                   "EMQX_DASHBOARD__DEFAULT_PASSWORD=" + json.dumps(values["emqxAdminPassword"])
                   + "\nEMQX_NODE__COOKIE=" + json.dumps(values["emqxNodeCookie"]) + "\n")
    _write_private(output / "api-keys.bootstrap",
                   values["emqxApiKey"] + ":" + values["emqxApiSecret"] + ":administrator\n",
                   mode=0o400, owner=(1000, 1000))


def _run(command, timeout=120, **kwargs):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        raise ProvisionError("Local database command failed or exceeded its deadline.") from None
    return result


def database(docker, assets, attempts=30):
    deadline = time.monotonic() + 60
    for attempt in range(attempts):
        # The official entrypoint's temporary init server is socket-only. Wait
        # for the final TCP listener before applying migrations to its database.
        if _run([docker, "exec", "ground-timescaledb", "pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "telemetry"], timeout=3).returncode == 0:
            break
        if attempt == attempts - 1 or time.monotonic() >= deadline:
            raise ProvisionError("Local telemetry database did not become available.")
        time.sleep(2)
    assets = Path(assets)
    schema = (assets / "create-telemetry-table.sql").read_text()
    # Keep the manual-install SQL as the single column definition. These exact
    # substitutions add repeatability without silently accepting a changed DDL.
    substitutions = {
        "CREATE TABLE telemetry_data (": "CREATE TABLE IF NOT EXISTS telemetry_data (",
        "SELECT create_hypertable('telemetry_data', 'time');":
            "SELECT create_hypertable('telemetry_data', 'time', if_not_exists => TRUE);",
        "CREATE INDEX idx_unit_id_time": "CREATE INDEX IF NOT EXISTS idx_unit_id_time",
    }
    for before, after in substitutions.items():
        if schema.count(before) != 1:
            raise ProvisionError("Telemetry schema requires provisioning review.")
        schema = schema.replace(before, after)
    sql = ("SET statement_timeout = '120s'; SET lock_timeout = '30s';\n"
           "SELECT pg_advisory_lock(7162738);\nBEGIN;\n"
           "DO $$ BEGIN IF current_setting('server_version_num')::int / 10000 <> 17 THEN "
           "RAISE EXCEPTION 'PostgreSQL 17 is required; review migration before changing major version'; "
           "END IF; END $$;\n"
           "CREATE EXTENSION IF NOT EXISTS timescaledb;\n" + schema + "\nCOMMIT;\n"
           + (assets / "migrations/001-hardware-availability.sql").read_text()
           + "\n" + (assets / "provisioning/roles.sql").read_text()
           + "\nSELECT pg_advisory_unlock(7162738);\n")
    result = _run([docker, "exec", "-i", "ground-timescaledb", "psql", "-X", "-U", "postgres",
                   "-d", "telemetry", "-v", "ON_ERROR_STOP=1"], input=sql)
    if result.returncode:
        raise ProvisionError("Telemetry schema/migration failed; ingestion remains unprovisioned.")


def build_assets(source, output):
    """Build public, immutable assets; credentials are resolved only at runtime."""
    source, output = Path(source), Path(output)
    for relative in ["create-telemetry-table.sql", "emqx_action.sql", "emqx_rule.sql",
                     "emqx_rule_fill_station.sql", "proto/telemetry.proto",
                     "migrations/001-hardware-availability.sql", "provisioning/roles.sql"]:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    datasource = {
        "apiVersion": 1,
        "datasources": [{
            "name": "Telemetry", "uid": "bfk1elo58d3pca", "type": "grafana-postgresql-datasource",
            "access": "proxy", "url": "127.0.0.1:5432", "user": "ground_reader", "database": "telemetry",
            "isDefault": True, "editable": False, "version": 1,
            "jsonData": {"database": "telemetry", "sslmode": "disable", "postgresVersion": 1700,
                         "timescaledb": True},
            "secureJsonData": {"password": "$CRT_DATABASE_PASSWORD"},
        }],
    }
    provider = {
        "apiVersion": 1,
        "providers": [{"name": "ground-telemetry", "orgId": 1, "folder": "Ground Station",
                       "type": "file", "disableDeletion": True, "allowUiUpdates": False,
                       "updateIntervalSeconds": 30, "options": {"path": "/var/lib/grafana/dashboards"}}],
    }
    dashboard = json.loads((source / "grafana.json").read_text())
    dashboard["id"] = None
    for panel in dashboard["panels"]:
        if panel["id"] == 1:
            panel["options"]["mode"] = "markdown"
            panel["options"]["content"] = "Camera feeds are not configured for this deployment."
        # The exported dashboard used a nonexistent timestamp column. The
        # flight hardware uptime is milliseconds; reset/duplicate times yield NULL.
        for target in panel.get("targets", []):
            if "rawSql" in target:
                target["rawSql"] = target["rawSql"].replace(
                    'NULLIF("timestamp" - lag("timestamp") OVER (ORDER BY time), 0)',
                    "NULLIF(GREATEST(ms_since_boot_cfc - lag(ms_since_boot_cfc) OVER (ORDER BY time), 0) / 1000.0, 0)")
    documents = {
        "grafana/provisioning/datasources/telemetry.yaml": datasource,
        "grafana/provisioning/dashboards/telemetry.yaml": provider,
        "grafana/dashboards/dashboard.json": dashboard,
    }
    for relative, document in documents.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document, indent=2) + "\n")
    hba = output / "database/pg_hba.conf"
    hba.parent.mkdir(parents=True, exist_ok=True)
    hba.write_text("local all postgres trust\nlocal all all reject\n"
                   "host all all 127.0.0.1/32 scram-sha-256\n"
                   "host all all ::1/128 scram-sha-256\n"
                   "host all all 0.0.0.0/0 reject\nhost all all ::0/0 reject\n")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None


def _local_url(url, allow_query=False):
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "http" or not ipaddress.ip_address(parsed.hostname).is_loopback
                or parsed.username or parsed.password or (parsed.query and not allow_query) or parsed.fragment):
            raise ValueError()
        parsed.port  # Validate numeric range before making a request.
    except (ValueError, TypeError):
        raise ProvisionError("Management requests require a literal loopback HTTP endpoint.") from None
    return parsed


def _http(url, method="GET", body=None, credentials=None):
    _local_url(url, allow_query=True)
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if credentials is not None:
        token = base64.b64encode(":".join(credentials).encode()).decode()
        headers["Authorization"] = "Basic " + token
    request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                     method=method, headers=headers)
    # Local administration must not inherit a workstation/service HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=5) as response:
            if response.status == 204:
                return 204, None
            raw = response.read(1048577)
            if len(raw) > 1048576 or "application/json" not in response.headers.get("Content-Type", ""):
                raise ProvisionError("Local management response has an unsupported size or type.")
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as error:
        error.close()
        return error.code, None
    except (OSError, ValueError):
        raise ProvisionError("Local management request failed or returned invalid JSON.") from None


def wait(url, attempts=25):
    _local_url(url)
    deadline = time.monotonic() + 60
    for attempt in range(attempts):
        try:
            status, value = _http(url)
            if status == 200 and isinstance(value, dict) and value.get("database") == "ok":
                return
        except ProvisionError:
            pass
        if attempt == attempts - 1 or time.monotonic() >= deadline:
            raise ProvisionError("Local Grafana did not report healthy storage before its deadline.")
        time.sleep(2)


def _topics_intersect(left, right):
    left, right = left.split("/"), right.split("/")
    for first, second in zip(left, right):
        if "#" in (first, second):
            return True
        if first != second and "+" not in (first, second):
            return False
    shortest = min(len(left), len(right))
    return len(left) == len(right) or left[shortest:] == ["#"] or right[shortest:] == ["#"]


def _rule_topics(sql):
    # Tokenize before locating FROM: strings and comments can contain convincing
    # fake clauses. This is deliberately a small inventory lexer, not a SQL
    # evaluator; ambiguous syntax fails closed for operator inventory.
    lexer = re.compile(r'''(?P<space>\s+)|(?P<comment>--[^\n]*|/\*.*?\*/)
        |(?P<string>'(?:[^'\\]|\\.|'')*')
        |(?P<topic>"(?:[^"\\]|\\.|"")*")
        |(?P<word>[A-Za-z_][A-Za-z_0-9]*)|(?P<symbol>.)''', re.VERBOSE | re.DOTALL)
    tokens = []
    for match in lexer.finditer(sql):
        kind, value = match.lastgroup, match.group()
        if kind in {"space", "comment"}:
            continue
        if kind == "symbol" and value in {"'", '"'}:
            raise ProvisionError("Cannot inventory ambiguous broker rule syntax.")
        tokens.append((kind, value))
    topics = []
    for index, (kind, value) in enumerate(tokens):
        if kind != "word" or value.upper() != "FROM":
            continue
        offset = index + 1
        while offset < len(tokens) and tokens[offset][0] == "topic":
            value = tokens[offset][1][1:-1]
            if "\\" in value or '"' in value:
                raise ProvisionError("Escaped broker topic filters require operator inventory.")
            topics.append(value)
            offset += 1
            if offset < len(tokens) and tokens[offset] == ("symbol", ","):
                offset += 1
    return topics


def broker(secrets_file, assets, api_url, attempts=15):
    parsed = _local_url(api_url)
    if parsed.path != "/api/v5":
        raise ProvisionError("Broker management endpoint must end at /api/v5.")
    values = load_secrets(secrets_file)
    credentials = (values["emqxApiKey"], values["emqxApiSecret"])
    deadline = time.monotonic() + 120

    def request(path, method="GET", body=None):
        if time.monotonic() >= deadline:
            raise ProvisionError("Broker provisioning exceeded its deadline.")
        return _http(api_url + path, method, body, credentials)

    # Match the e5.8.8 management API, never infer enterprise capabilities from
    # a mutable Docker tag or PostgreSQL authentication support alone.
    for attempt in range(attempts):
        try:
            status, types = request("/action_types")
            if status == 200:
                break
            if status not in {502, 503}:
                raise ProvisionError("Broker API credentials or capabilities are unavailable.")
        except ProvisionError:
            if attempt == attempts - 1:
                raise
        if attempt == attempts - 1:
            raise ProvisionError("Broker management API did not become available.")
        time.sleep(2)
    if not isinstance(types, list) or "pgsql" not in types:
        raise ProvisionError("Broker requires the PostgreSQL action capability; review edition/license.")
    if request("/schema_registry")[0] != 200:
        raise ProvisionError("Broker requires Schema Registry; review edition/license.")

    owned_ids = {"ground_telemetry_json", "ground_telemetry_protobuf"}
    for page in range(1, 11):
        status, rules = request(f"/rules?page={page}&limit=100")
        if status != 200 or not isinstance(rules, dict) or not isinstance(rules.get("data"), list):
            raise ProvisionError("Cannot inventory existing broker rules before provisioning.")
        for rule in rules["data"]:
            if rule.get("id") in owned_ids or rule.get("enable") is False:
                continue
            topics = _rule_topics(rule.get("sql", ""))
            if not topics or any(_topics_intersect(topic, managed)
                                 for topic in topics for managed in ("rats/raw/+", "rats/pb/0")):
                raise ProvisionError("An unmanaged broker rule may duplicate ingestion; inventory it first.")
        meta = rules.get("meta", {})
        if meta.get("hasnext") is False or ("hasnext" not in meta and len(rules["data"]) < 100):
            break
    else:
        raise ProvisionError("Broker rule inventory exceeds the supported bound.")

    def reconcile(collection, identifier, body, immutable):
        resource = collection + "/" + identifier
        status, _ = request(resource)
        if status == 404:
            status, _ = request(collection, "POST", body)
            expected = 201
        elif status == 200:
            status, _ = request(resource, "PUT", {key: value for key, value in body.items() if key not in immutable})
            expected = 200
        else:
            raise ProvisionError("Broker resource inventory failed.")
        if status != expected:
            raise ProvisionError("Broker resource reconciliation failed; inspect local service health.")

    assets = Path(assets)
    reconcile("/schema_registry", "telemetry", {
        "name": "telemetry", "type": "protobuf", "source": (assets / "proto/telemetry.proto").read_text(),
    }, {"name"})
    reconcile("/connectors", "pgsql:ground_telemetry", {
        "name": "ground_telemetry", "type": "pgsql", "enable": True,
        "server": "127.0.0.1:5432", "database": "telemetry", "username": "ground_ingest",
        "password": values["ingestPassword"], "pool_size": 8, "ssl": {"enable": False},
    }, {"type", "name"})
    reconcile("/actions", "pgsql:ground_telemetry", {
        "name": "ground_telemetry", "type": "pgsql", "enable": True, "connector": "ground_telemetry",
        "parameters": {"sql": (assets / "emqx_action.sql").read_text()},
    }, {"type", "name"})
    for identifier, filename in [("ground_telemetry_json", "emqx_rule.sql"),
                                 ("ground_telemetry_protobuf", "emqx_rule_fill_station.sql")]:
        reconcile("/rules", identifier, {"id": identifier, "enable": True,
                  "sql": (assets / filename).read_text(), "actions": ["pgsql:ground_telemetry"]}, {"id"})
    for attempt in range(attempts):
        integrations = [request(path) for path in ("/connectors/pgsql:ground_telemetry", "/actions/pgsql:ground_telemetry")]
        if all(status == 200 and isinstance(body, dict) and body.get("status") == "connected"
               for status, body in integrations):
            return
        if attempt == attempts - 1:
            raise ProvisionError("Broker database connector/action did not become healthy.")
        time.sleep(2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--secrets-file", required=True, type=Path)
    prep.add_argument("--output", required=True, type=Path)
    db = commands.add_parser("database")
    db.add_argument("--docker", required=True)
    db.add_argument("--assets", required=True, type=Path)
    assets = commands.add_parser("assets")
    assets.add_argument("--source", required=True, type=Path)
    assets.add_argument("--output", required=True, type=Path)
    health = commands.add_parser("wait")
    health.add_argument("--url", required=True)
    integration = commands.add_parser("broker")
    integration.add_argument("--secrets-file", required=True, type=Path)
    integration.add_argument("--assets", required=True, type=Path)
    integration.add_argument("--api-url", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args.secrets_file, args.output)
        elif args.command == "database":
            database(args.docker, args.assets)
        elif args.command == "assets":
            build_assets(args.source, args.output)
        elif args.command == "wait":
            wait(args.url)
        elif args.command == "broker":
            broker(args.secrets_file, args.assets, args.api_url)
    except ProvisionError as error:
        print("Telemetry provisioning failed: " + str(error), file=sys.stderr)
        return 1
    except OSError:
        print("Telemetry provisioning failed; inspect private configuration and local service health.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
