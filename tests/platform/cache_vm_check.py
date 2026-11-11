"""Guest-only acceptance for the real signed HTTP cache and isolated Nix stores."""
import argparse
import http.server
import json
from pathlib import Path
import subprocess
import urllib.request

STATE = Path("/var/lib/ground-cache-vm")
ORIGIN = "http://127.0.0.1:8080/cache"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def fetch(path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(ORIGIN + path, timeout=15) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    require(len(data) <= 4 * 1024 * 1024, "Fixture HTTP response exceeded its bound.")
    return data


class CorruptSignature(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond(send_body=True)

    def do_HEAD(self):
        self.respond(send_body=False)

    def respond(self, send_body):
        try:
            data = fetch(self.path)
            if self.path.endswith(".narinfo"):
                lines = data.decode().splitlines()
                changed = False
                for index, line in enumerate(lines):
                    if line.startswith("Sig: cache-vm.test:"):
                        prefix, signature = line.rsplit(":", 1)
                        lines[index] = prefix + ":" + ("B" if signature[0] == "A" else "A") + signature[1:]
                        changed = True
                require(changed, "Expected fixture signature was absent.")
                data = ("\n".join(lines) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if send_body:
                self.wfile.write(data)
        except Exception:
            self.send_error(502, "Fixture cache upstream unavailable")

    def log_message(self, *_args):
        pass


def command(arguments, *, success=True):
    result = subprocess.run(arguments, text=True, capture_output=True, timeout=90)
    if success and result.returncode:
        raise RuntimeError("Fixture command failed: " + result.stderr[-3000:])
    return result


def client(name, key):
    require(name.isalpha(), "Unexpected disposable client name.")
    root = STATE / "clients" / name
    root.mkdir(parents=True, exist_ok=True)
    uri = "local?root=" + str(root)
    options = ["--option", "trusted-public-keys", key, "--option", "secret-key-files", "",
               "--option", "require-sigs", "true", "--option", "substituters", "",
               "--option", "builders", "", "--option", "max-jobs", "0"]
    config = json.loads(command(["nix", "config", "show", "--json", *options]).stdout)
    for setting, expected in (("trusted-public-keys", [key]), ("secret-key-files", []),
                              ("require-sigs", True), ("substituters", []), ("max-jobs", 0)):
        require(config[setting]["value"] == expected, "Client configuration inherited unwanted settings.")
    return root, uri, options


def copy(uri, options, path, source=ORIGIN):
    return command(["nix", "copy", "--from", source, "--to", uri, *options, path], success=False)


def physical(root, path):
    require(path.startswith("/nix/store/"), "Unexpected fixture store path.")
    return root / path.lstrip("/")


def verify(root, fixtures):
    require((physical(root, fixtures["dependency"]) / "payload").read_text() == "dependency\n",
            "Client dependency contents differ.")
    require((physical(root, fixtures["artifact"]) / "payload").read_text() == "artifact\n",
            "Client artifact contents differ.")
    require((physical(root, fixtures["artifact"]) / "dependency").readlink()
            == Path(fixtures["dependency"]) / "payload", "Client closure reference differs.")


def run_phase(phase):
    fixtures = json.loads(Path("/etc/ground-cache-vm.json").read_text())
    key = (STATE / "cache.pub").read_text().strip()
    path = fixtures["artifact"]
    if phase == "verify":
        info = fetch("/" + Path(path).name.split("-", 1)[0] + ".narinfo").decode()
        require("\nSig: cache-vm.test:" in info, "HTTP metadata is not signed by the fixture key.")
        require(not any(line.startswith("CA:") for line in info.splitlines()),
                "Content-addressed fixtures cannot prove signature enforcement.")
        root, uri, options = client("trusted", key)
        require(not physical(root, path).exists(), "Positive client was not empty.")
        result = copy(uri, options, path)
        require(result.returncode == 0, "Trusted HTTP fetch failed: " + result.stderr[-2000:])
        verify(root, fixtures)
        print("PASS: signed nginx/Harmonia fetch and complete client closure.")

        wrong_key = (STATE / "unrelated.pub").read_text().strip()
        for name, trust, source in (("untrusted", wrong_key, ORIGIN),
                                    ("corrupted", key, "http://127.0.0.1:5001")):
            negative, destination, settings = client(name, trust)
            require(not physical(negative, path).exists(), "Negative client was not empty.")
            result = copy(destination, settings, path, source)
            require(result.returncode != 0 and "signature" in result.stderr.lower(),
                    "Invalid trust was not rejected specifically for its signature: " + result.stderr[-2000:])
            require(all(not physical(negative, fixtures[name]).exists()
                        for name in ("artifact", "dependency")), "Negative client accepted a fixture path.")
        print("PASS: unrelated trust and a corrupted signature both rejected in empty stores.")

        require(copy(uri, options, fixtures["control"]).returncode == 0, "Cannot import GC control.")
        require(physical(root, fixtures["control"]).exists(), "GC control was not present before collection.")
        # Every collector is explicitly restricted to this disposable store.
        gcroot = root / "nix/var/nix/gcroots/retained"
        gcroot.parent.mkdir(parents=True, exist_ok=True)
        command(["nix-store", "--store", uri, *options, "--add-root", str(gcroot), "--realise", path])
        command(["nix-store", "--store", uri, *options, "--gc"])
        verify(root, fixtures)
        require(not physical(root, fixtures["control"]).exists(), "GC did not collect the unrooted control.")
        print("PASS: isolated client GC retained rooted closure and removed the unrooted control.")
    elif phase == "outage":
        root, _, _ = client("trusted", key)
        verify(root, fixtures)
        empty, uri, options = client("outage", key)
        result = copy(uri, options, path)
        require(result.returncode != 0 and not physical(empty, path).exists(),
                "Fresh fetch unexpectedly succeeded during cache outage.")
        print("PASS: retained artifacts usable during cache outage; fresh fetch fails.")
    else:
        root, uri, options = client("restored" if phase == "restore" else "rebooted", key)
        require(not physical(root, path).exists(), "Reconnection client was not empty.")
        result = copy(uri, options, path)
        require(result.returncode == 0, "Reconnection HTTP fetch failed: " + result.stderr[-2000:])
        verify(root, fixtures)
        print("PASS: new clean client fetched without a builder or external substituter.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["proxy", "verify", "outage", "restore", "afterboot"])
    phase = parser.parse_args().phase
    if phase == "proxy":
        http.server.ThreadingHTTPServer(("127.0.0.1", 5001), CorruptSignature).serve_forever()
    else:
        run_phase(phase)


if __name__ == "__main__":
    main()
