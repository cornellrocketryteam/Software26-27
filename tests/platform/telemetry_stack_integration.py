"""Real, disposable telemetry stack acceptance; no devices or production state.

Prepare all four pinned images separately. Runtime never pulls images:
  python3 tests/platform/telemetry_stack_integration.py --docker docker \
    --images-file tests/platform/telemetry_test_images.json

The manifest is a test fixture, not deployment imagePins/archive hashes. The
Grafana version is discovered through /api/health rather than inferred from its
legacy tag. An Enterprise evaluation license is sufficient for these synthetic
tests; production license suitability and actual systemd/VM recovery are outside
this test. Every service shares a --network none client's loopback namespace.
There are no published host ports, host data binds, or Docker socket mounts.
"""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
if ROOT.name == "platform":
    ROOT = ROOT.parent.parent
COMPONENTS = ("timescaledb", "emqx", "grafana", "client")
NAMES = {name: "ground-" + name for name in COMPONENTS}
NAMES["client"] = "ground-telemetry-test-client"
FIXTURE = Path("/fixtures")
DATASOURCE = "bfk1elo58d3pca"
DASHBOARD = "adrc2lg"


class AcceptanceError(Exception):
    """Only fixed, credential-free diagnostics may cross the process boundary."""


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


def startup_failure_categories(log):
    """Classify explicit failure signatures; configured settings are not causes.

    Only fixed category names leave this function. In particular, the normal
    cookie warning/configuration banner must never imply a cookie failure.
    These are observed failure signatures, not a diagnosis of their root cause.
    """
    text = log.lower()
    patterns = {
        "QUIC NIF load failure": r"(?s)(?:quicer.{0,2000}nif_library_not_loaded|nif_library_not_loaded.{0,2000}quicer)",
        "cookie error": (
            r"\b(?:invalid|illegal|malformed)\s+(?:erlang\s+)?(?:distribution\s+)?cookie\b"
            r"|\bcookie[^\n]{0,80}\bmust not contain\b"
            r"|\bcookie[^\n]{0,80}\b(?:is invalid|is illegal|is malformed)\b"
        ),
        "configuration parse error": r"parse_error|failed_to_parse|syntax error|translation_error",
        "filesystem permission error": r"\beacces\b|permission denied",
        "VM resource/execution error": (
            r"failed to create[^\n]{0,80}(?:thread|scheduler)|cannot allocate memory"
            r"|illegal instruction|segmentation fault|qemu[^\n]{0,80}(?:uncaught target signal|fatal error)"
        ),
    }
    return [category for category, pattern in patterns.items() if re.search(pattern, text)]


def check_startup_classifier():
    # Regression: a normal credential banner previously hid the actual QUIC NIF
    # startup error. Samples contain no credentials, log bodies, or device data.
    warning = "WARNING: Erlang distribution cookie is insecure. EMQX_NODE__COOKIE=[hidden]"
    samples = [
        (warning, []),
        ("EMQX_NODE__COOKIE=[hidden]; quicer configured; qemu environment", []),
        (warning + "\nfailed_to_start_app,quicer,{error,nif_library_not_loaded}", ["QUIC NIF load failure"]),
        ("ERROR: Erlang distribution cookie must not contain whitespace", ["cookie error"]),
        ("ERROR: invalid cookie", ["cookie error"]),
        ("Failed to create scheduler thread", ["VM resource/execution error"]),
    ]
    for text, expected in samples:
        require(startup_failure_categories(text) == expected, "Startup classifier regression failed.")


def load_runtime(path):
    spec = importlib.util.spec_from_file_location("telemetry_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def poll(check, message, timeout=100):
    deadline = time.monotonic() + timeout
    while True:
        if check():
            return
        if time.monotonic() >= deadline:
            raise AcceptanceError(message)
        time.sleep(1)


def synthetic_packets(cycle):
    # All data is synthetic. Explicit zeros distinguish an available zero reading
    # from an unavailable reading normalized to SQL NULL by the database trigger.
    proto = (FIXTURE / "assets/proto/telemetry.proto").read_text()
    fields = re.findall(r"\b(fixed32|uint32|uint64|int32|double|bool)\s+(\w+)\s*=\s*(\d+)\s*;", proto)
    require(bool(fields), "Synthetic protobuf field inventory is empty.")
    base = {name: False if kind == "bool" else 0 for kind, name, _ in fields}
    cases = [("json", 0, None, 0, 0), ("json", 1, 1, 0, 0),
             ("protobuf", 0, 1, 0, 0), ("protobuf", 0, 1, 4095, 7),
             ("protobuf", 0, 1, 18, 2), ("protobuf", 0, 2, 0, 0),
             ("protobuf", 0, None, 0, 0)]
    for index, (encoding, unit, version, configured, valid) in enumerate(cases):
        packet = dict(base, pressure=870000 + cycle * 100 + index,
                      ms_since_boot_fill=1000 + cycle * 100 + index)
        if version is None:
            for name in ("availability_version", "configured_devices_mask", "valid_readings_mask"):
                packet.pop(name)
        else:
            packet.update(availability_version=version, configured_devices_mask=configured,
                          valid_readings_mask=valid)
        zero = [0, 0, 0, False, False, False, 0]
        readings = ([None] * 7 if index == 2 else
                    [None, 0, None, None, False, False, None] if index == 4 else zero)
        expected = [unit, version or 0, configured, valid, *readings]
        if encoding == "json":
            packet["timestamp"] = packet.pop("gps_time")
            yield f"rats/raw/{unit}", json.dumps(packet).encode(), expected
        else:
            encoded = bytearray()
            for kind, name, number in fields:
                if name not in packet:
                    continue
                value = packet[name]
                wire = 1 if kind == "double" else 5 if kind == "fixed32" else 0
                encoded.extend(varint(int(number) * 8 + wire))
                encoded.extend(struct.pack("<d", value) if kind == "double" else
                               struct.pack("<I", value) if kind == "fixed32" else varint(int(value)))
            yield "rats/pb/0", bytes(encoded), expected


def varint(value):
    output = bytearray()
    while value > 127:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return output


def mqtt_publish(cycle):
    def text(value):
        value = value.encode()
        return struct.pack("!H", len(value)) + value

    def exact(stream, count):
        value = bytearray()
        while len(value) < count:
            part = stream.recv(count - len(value))
            require(bool(part), "Synthetic MQTT peer closed its connection.")
            value.extend(part)
        return bytes(value)

    with socket.create_connection(("127.0.0.1", 1883), timeout=5) as stream:
        payload = text("MQTT") + b"\x04\x02\x00\x1e" + text("isolated-synthetic-acceptance")
        stream.sendall(b"\x10" + varint(len(payload)) + payload)
        require(exact(stream, 4) == b"\x20\x02\x00\x00", "Synthetic MQTT CONNECT was rejected.")
        for identifier, (topic, data, _) in enumerate(synthetic_packets(cycle), 1):
            payload = text(topic) + struct.pack("!H", identifier) + data
            stream.sendall(b"\x32" + varint(len(payload)) + payload)
            require(exact(stream, 4) == b"\x40\x02" + struct.pack("!H", identifier),
                    "Synthetic MQTT QoS1 publish was not acknowledged.")
        stream.sendall(b"\xe0\x00")


def client_phase(phase, cycle):
    runtime = load_runtime(FIXTURE / "runtime.py")
    private = FIXTURE / "secrets.json"
    assets = FIXTURE / "assets"
    if phase == "prepare":
        interfaces = [Path("/sys/class/net") / name for _, name in socket.if_nameindex()]
        require(all(path.name == "lo" or not int((path / "flags").read_text().strip(), 16) & 1
                    for path in interfaces), "Fixture namespace has an active non-loopback interface.")
        require(not (Path("/proc/net/route").read_text().splitlines()[1:]),
                "Fixture namespace has a non-loopback route.")
        require(not any(parts[0] == "0" * 32 and parts[1] == "00" and parts[-1] != "lo"
                        for parts in (line.split() for line in Path("/proc/net/ipv6_route").read_text().splitlines())),
                "Fixture namespace has a non-loopback IPv6 default route.")
        runtime.prepare(private, FIXTURE / "runtime")
        runtime.prepare(private, FIXTURE / "runtime")
        os.link(FIXTURE / "runtime/api-keys.bootstrap", FIXTURE / "api-keys.bootstrap")
        bootstrap = (FIXTURE / "api-keys.bootstrap").stat()
        require(bootstrap.st_uid == 1000 and bootstrap.st_gid == 1000
                and bootstrap.st_mode & 0o777 == 0o400,
                "Real Linux API bootstrap ownership/mode is wrong.")
        require((FIXTURE / "runtime").stat().st_mode & 0o777 == 0o700,
                "Private runtime directory permissions are wrong.")
        # The only fixture adaptation: Grafana reads its dashboard in this
        # read-only volume. Do not rewrite credentials or datasource contents.
        provider_path = assets / "grafana/provisioning/dashboards/telemetry.yaml"
        provider = json.loads(provider_path.read_text())
        provider["providers"][0]["options"]["path"] = "/fixtures/assets/grafana/dashboards"
        provider_path.write_text(json.dumps(provider))
        for name, uid in (("emqx-data", 1000), ("emqx-log", 1000), ("grafana", 472)):
            os.chown("/state/" + name, uid, uid)
    elif phase == "broker":
        # A cold emulated Enterprise VM can exceed the helper's first retry
        # window. Wait for the service here, then exercise the real helper;
        # automatic systemd retries are tested separately by the parent.
        def broker_ready():
            try:
                status, value = runtime._http("http://127.0.0.1:18083/status?format=json")
                return status == 200 and value.get("app_status") == "running"
            except runtime.ProvisionError:
                return False

        poll(broker_ready, "EMQX did not become ready on isolated loopback.", timeout=120)
        original_http = runtime._http
        last_request = "no management request"

        def observed_http(url, method="GET", body=None, credentials=None):
            nonlocal last_request
            # Only operation, fixed local path, and status escape the fixture.
            path = url.split("18083", 1)[-1].split("?", 1)[0]
            last_request = method + " " + path + " transport failure"
            result = original_http(url, method, body, credentials)
            last_request = method + " " + path + " HTTP " + str(result[0])
            return result

        runtime._http = observed_http
        try:
            runtime.broker(private, assets, "http://127.0.0.1:18083/api/v5")
        except runtime.ProvisionError:
            raise AcceptanceError("Broker helper failed after " + last_request + ".") from None
    elif phase == "inventory":
        values = runtime.load_secrets(private)
        auth = (values["emqxApiKey"], values["emqxApiSecret"])

        def get(path):
            status, body = runtime._http("http://127.0.0.1:18083/api/v5" + path, credentials=auth)
            require(status == 200, "Broker inventory GET failed (HTTP status only).")
            return body

        require(set(get("/action_types")) >= {"pgsql"}, "PostgreSQL action capability is absent.")
        require([item["name"] for item in get("/schema_registry")] == ["telemetry"],
                "Schema inventory contains unexpected resources.")
        for collection in ("connectors", "actions"):
            items = get("/" + collection)
            require(len(items) == 1 and items[0]["name"] == "ground_telemetry"
                    and items[0]["type"] == "pgsql" and items[0]["status"] == "connected",
                    "Connector/action inventory or health differs from the owned fixture.")
        connector = get("/connectors/pgsql:ground_telemetry")
        require(connector["username"] == "ground_ingest"
                and connector["server"] == "127.0.0.1:5432"
                and connector["database"] == "telemetry", "Connector does not use the ingest role.")
        require(get("/schema_registry/telemetry")["source"] == (assets / "proto/telemetry.proto").read_text(),
                "Registered protobuf differs from the asset.")
        action = get("/actions/pgsql:ground_telemetry")
        require(action["connector"] == "ground_telemetry"
                and action["parameters"]["sql"] == (assets / "emqx_action.sql").read_text(),
                "Shared action differs from the SQL asset.")
        rules = get("/rules?limit=100")["data"]
        files = {"ground_telemetry_json": "emqx_rule.sql",
                 "ground_telemetry_protobuf": "emqx_rule_fill_station.sql"}
        require({rule["id"] for rule in rules} == set(files) and len(rules) == 2,
                "Rule reconciliation changed the number of owned resources.")
        for rule in rules:
            require(rule["sql"] == (assets / files[rule["id"]]).read_text()
                    and rule["enable"] and rule["actions"] == ["pgsql:ground_telemetry"],
                    "A reconciled rule differs from its SQL asset or shared action.")
        status, status_body = runtime._http("http://127.0.0.1:18083/status?format=json")
        require(status == 200 and status_body["rel_vsn"] == "e5.8.8", "EMQX version/edition is unexpected.")
        license_info = get("/license")
        require(license_info.get("expiry") is False, "The evaluation fixture license is expired.")
    elif phase == "publish":
        mqtt_publish(cycle)
    elif phase == "grafana":
        runtime.wait("http://127.0.0.1:3000/grafana/api/health")
        values = runtime.load_secrets(private)
        auth = ("admin", values["grafanaAdminPassword"])

        def get(path, credentials=auth):
            status, body = runtime._http("http://127.0.0.1:3000/grafana/api/" + path,
                                         credentials=credentials)
            require(status == 200, "Grafana API check failed (HTTP status only).")
            return body

        health = get("health", None)
        require(health["database"] == "ok", "Grafana storage is unhealthy.")
        datasource = get("datasources/uid/" + DATASOURCE)
        require(datasource["user"] == "ground_reader"
                and datasource["url"] == "127.0.0.1:5432"
                and datasource.get("secureJsonFields", {}).get("password") is True,
                "Grafana datasource role, address, or secret provisioning is wrong.")
        require(get("datasources/uid/" + DATASOURCE + "/health").get("status") == "OK",
                "Grafana could not authenticate/query through its PostgreSQL datasource.")
        require(get("dashboards/uid/" + DASHBOARD, None)["dashboard"]["uid"] == DASHBOARD,
                "Anonymous Viewer cannot read the provisioned dashboard.")
        version = health.get("version", "unknown")
        require(bool(re.fullmatch(r"[A-Za-z0-9.+_-]{1,64}", version)), "Grafana version field is invalid.")
        print("Grafana health version: " + version, flush=True)


class Docker:
    def __init__(self, executable):
        self.executable = executable

    def run(self, *command, data=None, check=True, timeout=180):
        try:
            result = subprocess.run([self.executable, *command], input=data,
                                    capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            raise AcceptanceError("Docker operation failed or exceeded its deadline.") from None
        if check and result.returncode:
            # Never print argv, stdout, stderr, inspect Env, or HTTP bodies.
            raise AcceptanceError("Docker operation failed; exit status " + str(result.returncode) + ".")
        return result

    def json(self, *command):
        return json.loads(self.run(*command).stdout)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--images-file", type=Path)
    for component in COMPONENTS:
        parser.add_argument("--" + component + "-image")
    parser.add_argument("--client-phase", choices=("prepare", "broker", "inventory", "publish", "grafana"),
                        help=argparse.SUPPRESS)
    parser.add_argument("--cycle", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.client_phase:
        return args, None
    if args.images_file:
        require(not any(getattr(args, c + "_image") for c in COMPONENTS),
                "Choose a manifest or four explicit image pins, not both.")
        pins = json.loads(args.images_file.read_text())
        require(set(pins) == {*COMPONENTS, "platform"},
                "Image manifest must contain exactly four component pins and platform declarations.")
        declaration = pins.pop("platform")
        args.platforms = ({name: declaration for name in COMPONENTS}
                          if isinstance(declaration, str) else declaration)
    else:
        pins = {c: getattr(args, c + "_image") for c in COMPONENTS}
        args.platforms = {name: "linux/amd64" for name in COMPONENTS}
    require(isinstance(args.platforms, dict) and set(args.platforms) == set(COMPONENTS)
            and all(value in {"linux/amd64", "linux/arm64"} for value in args.platforms.values()),
            "Platforms must explicitly identify Linux amd64 or arm64 for every component.")
    require(all(isinstance(pin, str) and re.fullmatch(r"[a-z0-9./_-]+@sha256:[a-f0-9]{64}", pin)
                for pin in pins.values()), "All four images require immutable repository@sha256 pins.")
    return args, pins


def stack(args, pins):
    check_startup_classifier()
    docker = Docker(args.docker)
    runtime = load_runtime(ROOT / "ground-station/provisioning/runtime.py")
    token = uuid.uuid4().hex
    label = "crt.telemetry-acceptance=" + token
    volumes = {part: "ground-telemetry-test-" + token + "-" + part
               for part in ("fixtures", "db", "emqx-data", "emqx-log", "grafana")}
    created, created_volumes = {}, []
    stage = "preflight"

    def phase(name, cycle=0):
        result = docker.run("exec", "-i", created["client"], "python", "/fixtures/stack_test.py",
                            "--client-phase", name, "--cycle", str(cycle), check=False, timeout=300)
        if result.returncode:
            if name == "broker":
                state = docker.json("container", "inspect", created["emqx"])[0]["State"]
                if not state["Running"]:
                    log = docker.run("logs", "--tail", "100", created["emqx"], check=False)
                    # Classify startup text in memory; never forward the logs.
                    text = (log.stdout + log.stderr).decode(errors="replace")
                    categories = startup_failure_categories(text)
                    raise AcceptanceError("EMQX exited " + str(state["ExitCode"]) + "; startup categories: "
                                          + (", ".join(categories) or "unclassified") + ".")
            # Client script emits fixed diagnostics, but never blindly forward
            # output from a dependency. Only allow our exact known messages.
            safe = result.stderr.decode(errors="replace").strip()
            if safe.startswith("FAIL: ") and len(safe) <= 240 and "\n" not in safe:
                raise AcceptanceError(safe[6:])
            raise AcceptanceError("Client phase " + name + " failed; exit status " + str(result.returncode) + ".")
        if name == "grafana":
            line = result.stdout.decode(errors="replace").strip()
            if re.fullmatch(r"Grafana health version: [A-Za-z0-9.+_-]{1,64}", line):
                print(line, flush=True)

    def start(component, options, command=()):
        # Record the ID before starting so failed starts are cleaned up, too.
        identifier = docker.run("create", "--name", NAMES[component], "--label", label,
                                "--platform", args.platforms[component], "--pull", "never", *options,
                                pins[component], *command).stdout.decode().strip()
        require(bool(re.fullmatch(r"[a-f0-9]{64}", identifier)), "Docker returned an invalid created ID.")
        created[component] = identifier
        docker.run("start", identifier)

    def sql(statement):
        return docker.run("exec", "-i", created["timescaledb"], "psql", "-X", "-U", "postgres",
                          "-d", "telemetry", "-v", "ON_ERROR_STOP=1", "-At",
                          data=statement.encode()).stdout.decode().strip()

    def check_authentication():
        def authenticate(user, password_variable=None, wrong=False, local=False):
            # Values stay in the container environment, never argv or output.
            setup = ("PGPASSWORD=invalid-isolated-password; export PGPASSWORD; " if wrong else
                     'PGPASSWORD="$' + password_variable + '"; export PGPASSWORD; '
                     if password_variable else "unset PGPASSWORD; ")
            command = ["psql", "-X", "-w", "-U", user, "-d", "telemetry", "-At",
                       "-v", "ON_ERROR_STOP=1"]
            if not local:
                command.extend(["-h", "127.0.0.1", "-p", "5432"])
            return docker.run("exec", "-i", created["timescaledb"], "sh", "-c",
                              setup + "exec " + " ".join(command),
                              data=b"SELECT current_user;\n", check=False)

        credentials = {"postgres": "POSTGRES_PASSWORD", "ground_ingest": "CRT_INGEST_PASSWORD",
                       "ground_reader": "CRT_READER_PASSWORD"}
        for user, variable in credentials.items():
            positive = authenticate(user, variable)
            require(positive.returncode == 0 and positive.stdout.decode().strip() == user,
                    "Correct role credential failed TCP authentication.")
            missing = authenticate(user)
            require(missing.returncode != 0 and b"no password supplied" in missing.stderr,
                    "A TCP role accepted a missing password or failed for an unrelated reason.")
            wrong = authenticate(user, wrong=True)
            require(wrong.returncode != 0 and b"password authentication failed" in wrong.stderr,
                    "A TCP role accepted a wrong password or failed for an unrelated reason.")
            for other_variable in set(credentials.values()) - {variable}:
                crossed = authenticate(user, other_variable)
                require(crossed.returncode != 0 and b"password authentication failed" in crossed.stderr,
                        "Role passwords are not independent at the TCP authentication boundary.")
        for user in ("ground_ingest", "ground_reader"):
            rejected = authenticate(user, local=True)
            require(rejected.returncode != 0 and b"pg_hba.conf rejects connection" in rejected.stderr,
                    "A non-admin role was not rejected on the local trust boundary.")

    def rows(cycles):
        columns = "unit_id,availability_version,configured_devices_mask,valid_readings_mask,pt_1_pressure,pt_2_pressure,load_cell,ball_valve_open,sv_1_open,ignition,qd_state"
        result = sql("SELECT row_to_json(t) FROM (SELECT " + columns + " FROM telemetry_data ORDER BY pressure) t;")
        actual = [list(json.loads(row).values()) for row in result.splitlines()]
        # Same fixture generator runs without needing /fixtures on the host.
        global FIXTURE
        original = FIXTURE
        try:
            FIXTURE = assets.parent
            expected = [expected for cycle in range(cycles) for _, _, expected in synthetic_packets(cycle)]
        finally:
            FIXTURE = original
        require(actual == expected, "Synthetic telemetry rows differ: routing, NULL/zero, persistence, or duplicates.")

    def network_check():
        for component, identifier in created.items():
            details = docker.json("container", "inspect", identifier)[0]
            host = details["HostConfig"]
            expected = "none" if component == "client" else "container:" + created["client"]
            require(host["NetworkMode"] == expected and not host.get("PortBindings")
                    and not host.get("PublishAllPorts") and not host.get("Privileged")
                    and not host.get("Devices"), "Container isolation or port settings differ from the fixture.")
            require(all(mount["Type"] == "volume" and mount["Name"] in created_volumes
                        for mount in details["Mounts"]), "Container has a host bind or unowned volume.")

    try:
        docker.run("info", "--format", "{{.ServerVersion}}")
        existing = set(docker.run("container", "ls", "--all", "--format", "{{.Names}}").stdout.decode().splitlines())
        require(not existing.intersection(NAMES.values()), "Reserved fixture container name exists; refusing to reuse or remove it.")
        existing_volumes = set(docker.run("volume", "ls", "--format", "{{.Name}}").stdout.decode().splitlines())
        require(not existing_volumes.intersection(volumes.values()), "Fixture volume name already exists.")
        for component, pin in pins.items():
            details = docker.json("image", "inspect", pin)[0]
            require(details["Os"] + "/" + details["Architecture"] == args.platforms[component],
                    "A prepared image does not match its declared platform.")
        print("PASS: all four immutable images match declared platforms; names are free; runtime pulls disabled.", flush=True)
        if set(args.platforms.values()) != {"linux/amd64"}:
            print("SCOPE: mixed/native ARM functional test; this does not establish native UM560 acceptance.", flush=True)
        stage = "fixture preparation"
        for volume in volumes.values():
            # This random name was checked absent; ownership is labelled.
            docker.run("volume", "create", "--label", label, volume)
            created_volumes.append(volume)
        mounts = ["--mount", "type=volume,src=" + volumes["fixtures"] + ",dst=/fixtures"]
        for part in ("emqx-data", "emqx-log", "grafana"):
            mounts.extend(["--mount", "type=volume,src=" + volumes[part] + ",dst=/state/" + part])
        start("client", ["--network", "none", *mounts],
              ["python", "-c", "import time; time.sleep(86400)"])
        with tempfile.TemporaryDirectory(prefix="telemetry-stack-") as temporary:
            work = Path(temporary)
            assets = work / "assets"
            runtime.build_assets(ROOT / "ground-station", assets)
            require((assets / "database/pg_hba.conf").is_file(), "The immutable database HBA asset is missing.")
            source = work / "runtime.py"
            source.write_bytes((ROOT / "ground-station/provisioning/runtime.py").read_bytes())
            secret_values = {key: secrets.token_urlsafe(32) for key in runtime.SECRET_KEYS}
            require({"ingestPassword", "readerPassword"} <= set(secret_values),
                    "The helper does not yet implement distinct database role passwords.")
            for key in ("databasePassword", "ingestPassword", "readerPassword", "grafanaAdminPassword",
                        "emqxAdminPassword", "emqxNodeCookie"):
                secret_values[key] += "-$literal'\"\\:=# space"
            secret_file = work / "secrets.json"
            secret_file.write_text(json.dumps(secret_values))
            secret_file.chmod(0o600)
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w") as tar:
                for path, name in ((assets, "assets"), (source, "runtime.py"),
                                   (secret_file, "secrets.json"), (Path(__file__), "stack_test.py")):
                    tar.add(path, arcname=name)
            docker.run("exec", "-i", created["client"], "python", "-c",
                       "import sys,tarfile,os; os.chmod('/fixtures',0o755); "
                       "tarfile.open(fileobj=sys.stdin.buffer,mode='r|').extractall('/fixtures',filter='data')",
                       data=archive.getvalue())
            phase("prepare")
            docker.run("exec", "--user", "1000:1000", created["client"], "python", "-c",
                       "import os; open('/fixtures/api-keys.bootstrap').close(); "
                       "assert not os.access('/fixtures/runtime',os.R_OK|os.X_OK); "
                       "assert not os.access('/fixtures/secrets.json',os.R_OK)")
            env_paths = {}
            for component, filename in (("timescaledb", "database.env"), ("emqx", "emqx.env"), ("grafana", "grafana.env")):
                target = work / filename
                docker.run("cp", created["client"] + ":/fixtures/runtime/" + filename, str(target))
                target.chmod(0o600)
                env_paths[component] = target
            print("PASS: root-only secrets/runtime and UID1000 mode0400 bootstrap; literal env files copied privately.", flush=True)
            shared = ["--network", "container:" + created["client"]]

            def service_options(component):
                return [*shared, "--env-file", str(env_paths[component])]

            stage = "database bootstrap and grants"
            start("timescaledb", [*service_options("timescaledb"),
                  "--mount", "type=volume,src=" + volumes["fixtures"] + ",dst=/fixtures,readonly",
                  "--mount", "type=volume,src=" + volumes["db"] + ",dst=/pgdata",
                  # Suppress the image's otherwise implicit anonymous VOLUME;
                  # PostgreSQL still uses the module's explicit /pgdata path.
                  "--mount", "type=volume,src=" + volumes["db"] + ",dst=/var/lib/postgresql/data",
                  "--env", "POSTGRES_USER=postgres", "--env", "POSTGRES_DB=telemetry",
                  "--env", "PGDATA=/pgdata", "--env", "TIMESCALEDB_TELEMETRY=off"],
                  ["postgres", "-c", "listen_addresses=127.0.0.1", "-c", "port=5432",
                   "-c", "hba_file=/fixtures/assets/database/pg_hba.conf"])
            runtime.database(args.docker, assets)
            check_authentication()
            require(sql("SELECT has_table_privilege('ground_ingest','telemetry_data','INSERT') "
                        "AND NOT has_table_privilege('ground_ingest','telemetry_data','SELECT') "
                        "AND NOT has_table_privilege('ground_ingest','telemetry_data','UPDATE') "
                        "AND NOT has_table_privilege('ground_ingest','telemetry_data','DELETE') "
                        "AND has_table_privilege('ground_reader','telemetry_data','SELECT') "
                        "AND NOT has_table_privilege('ground_reader','telemetry_data','INSERT') "
                        "AND NOT has_table_privilege('ground_reader','telemetry_data','UPDATE') "
                        "AND NOT has_table_privilege('ground_reader','telemetry_data','DELETE');") == "t",
                    "Database ingest/reader grants are not separated.")
            print("PASS: distinct-role TCP authentication, missing/wrong/cross-role password rejection, HBA and grants.", flush=True)
            stage = "EMQX startup and reconciliation"
            start("emqx", [*service_options("emqx"), "--user", "1000:1000",
                  "--mount", "type=volume,src=" + volumes["fixtures"] + ",dst=/fixtures,readonly",
                  "--mount", "type=volume,src=" + volumes["emqx-data"] + ",dst=/opt/emqx/data",
                  "--mount", "type=volume,src=" + volumes["emqx-log"] + ",dst=/opt/emqx/log",
                  "--env", "EMQX_NODE__NAME=emqx@127.0.0.1",
                  "--env", "EMQX_DASHBOARD__LISTENERS__HTTP__BIND=127.0.0.1:18083",
                  "--env", "EMQX_DASHBOARD__LISTENERS__HTTPS__BIND=0",
                  "--env", "EMQX_LISTENERS__TCP__DEFAULT__BIND=127.0.0.1:1883",
                  "--env", "EMQX_LISTENERS__SSL__DEFAULT__ENABLE=false",
                  "--env", "EMQX_LISTENERS__WS__DEFAULT__ENABLE=false",
                  "--env", "EMQX_LISTENERS__WSS__DEFAULT__ENABLE=false",
                  "--env", "EMQX_API_KEY__BOOTSTRAP_FILE=/fixtures/api-keys.bootstrap"])
            phase("broker")
            phase("broker")
            phase("inventory")
            print("PASS: EMQX e5.8.8 Enterprise bootstrap and twice-reconciled five owned resources.", flush=True)
            stage = "Grafana startup and datasource authentication"
            grafana_env = {
                "GF_SERVER_HTTP_ADDR": "127.0.0.1", "GF_SERVER_HTTP_PORT": "3000",
                "GF_SERVER_ROOT_URL": "http://127.0.0.1:3000/grafana/", "GF_SERVER_SERVE_FROM_SUB_PATH": "true",
                "GF_SECURITY_ALLOW_EMBEDDING": "true", "GF_SECURITY_DISABLE_GRAVATAR": "true",
                "GF_AUTH_ANONYMOUS_ENABLED": "true", "GF_AUTH_ANONYMOUS_ORG_ROLE": "Viewer",
                "GF_USERS_ALLOW_SIGN_UP": "false", "GF_DASHBOARDS_MIN_REFRESH_INTERVAL": "125ms",
                "GF_PLUGINS_PREINSTALL_DISABLED": "true", "GF_PLUGINS_PREINSTALL": "", "GF_INSTALL_PLUGINS": "",
                "GF_ANALYTICS_REPORTING_ENABLED": "false", "GF_ANALYTICS_CHECK_FOR_UPDATES": "false",
                "GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES": "false", "GF_PANELS_DISABLE_SANITIZE_HTML": "false",
                "GF_PATHS_PROVISIONING": "/fixtures/assets/grafana/provisioning",
            }
            options = [*service_options("grafana"), "--user", "472:472",
                       "--mount", "type=volume,src=" + volumes["fixtures"] + ",dst=/fixtures,readonly",
                       "--mount", "type=volume,src=" + volumes["grafana"] + ",dst=/var/lib/grafana"]
            for key, value in grafana_env.items():
                options.extend(["--env", key + "=" + value])
            start("grafana", options)
            phase("grafana")
            network_check()
            stage = "synthetic MQTT ingestion"
            phase("publish", 0)
            poll(lambda: sql("SELECT count(*) FROM telemetry_data;") == "7", "Synthetic telemetry did not reach seven rows.")
            rows(1)
            print("PASS: real JSON/protobuf MQTT ingestion, seven NULL/zero cases, reader datasource/dashboard, isolation.", flush=True)
            stage = "persistent service restart recovery"
            docker.run("restart", "--time", "15", created["timescaledb"])
            runtime.database(args.docker, assets)
            check_authentication()
            docker.run("restart", "--time", "15", created["emqx"])
            phase("broker")
            phase("broker")
            phase("inventory")
            docker.run("restart", "--time", "15", created["grafana"])
            phase("grafana")
            rows(1)
            phase("publish", 1)
            poll(lambda: sql("SELECT count(*) FROM telemetry_data;") == "14", "Restart telemetry did not reach fourteen rows.")
            # Allow any accidental duplicate ingestion to settle before exact comparison.
            time.sleep(2)
            rows(2)
            network_check()
            print("PASS: DB/EMQX/Grafana restarts, repeated reconciliation, fourteen persistent rows without duplicates.", flush=True)
    except Exception as error:
        message = str(error) if isinstance(error, (AcceptanceError, runtime.ProvisionError)) else "Unexpected fixture failure (details suppressed)."
        raise AcceptanceError(stage + ": " + message) from None
    finally:
        cleanup_failed = False
        for identifier in reversed(list(created.values())):
            try:
                result = docker.run("rm", "--force", "--volumes", identifier, check=False)
                cleanup_failed |= result.returncode != 0
            except AcceptanceError:
                cleanup_failed = True
        for volume in reversed(created_volumes):
            try:
                cleanup_failed |= docker.run("volume", "rm", volume, check=False).returncode != 0
            except AcceptanceError:
                cleanup_failed = True
        if cleanup_failed:
            print("FAIL: disposable fixture cleanup incomplete; inspect crt.telemetry-acceptance labels.", file=sys.stderr)
        elif created:
            print("PASS: removed only containers/volumes created by this test.", flush=True)
        if cleanup_failed and sys.exc_info()[0] is None:
            raise AcceptanceError("Disposable fixture cleanup failed.")


def main():
    try:
        args, pins = parse_args()
        if args.client_phase:
            client_phase(args.client_phase, args.cycle)
        else:
            stack(args, pins)
    except AcceptanceError as error:
        print("FAIL: " + str(error), file=sys.stderr)
        return 1
    except Exception:
        print("FAIL: unexpected acceptance error; private details suppressed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
