# Actual nginx routing tests without a VM, device, internet or service activation.
# nix build --impure --expr 'let pkgs = import /path/to/nixpkgs {
#   system = builtins.currentSystem; }; in import ./tests/platform/test_operator_ui_serving.nix { inherit pkgs; }'
{ pkgs }:
let
  lib = pkgs.lib;
  assets = pkgs.runCommand "operator-ui-route-fixtures" { } ''
    mkdir -p "$out/assets"
    printf '<html>operator-route-fixture</html>' > "$out/index.html"
    printf 'console.log("bundled-asset")' > "$out/assets/app.js"
    printf '{"untrustedBundledDefault":true}' > "$out/station-config.json"
  '';
  tiles = pkgs.writeTextDir "0/0/0.png" "local-tile-fixture";
  evaluate = directory: (import (pkgs.path + "/nixos/lib/eval-config.nix") {
    system = pkgs.stdenv.hostPlatform.system;
    modules = [
      ../../nix/nixos-configurations/ground-station
      {
        nixpkgs.pkgs = pkgs;
        groundStation.operatorUi = {
          enable = true;
          package = assets;
          tilesDirectory = directory;
          fillStationWebSocketUrl = "ws://fill.test/socket";
        };
        services.nginx.logError = "stderr";
        services.nginx.commonHttpConfig = "access_log off;";
      }
    ];
  }).config;
  unconfigured = evaluate null;
  configured = evaluate (toString tiles);
in
pkgs.runCommand "ground-operator-ui-serving-tests" {
  nativeBuildInputs = [ pkgs.python3 pkgs.nginx ];
} ''
  export PYTHONDONTWRITEBYTECODE=1
  export NGINX_UNCONFIGURED=${unconfigured.environment.etc."nginx/nginx.conf".source}
  export NGINX_CONFIGURED=${configured.environment.etc."nginx/nginx.conf".source}
  python - <<'PY'
  import json
  import os
  import pathlib
  import socket
  import subprocess
  import time
  import urllib.error
  import urllib.request

  def request(base, path):
      try:
          response = urllib.request.urlopen(base + path, timeout=2)
      except urllib.error.HTTPError as error:
          response = error
      with response:
          return response.status, response.headers, response.read()

  for scenario, directory_configured in [("UNCONFIGURED", False), ("CONFIGURED", True)]:
      work = pathlib.Path.cwd() / scenario.lower()
      work.mkdir()
      for name in ["run", "logs", "cache", "spool"]:
          (work / name).mkdir()
      with socket.socket() as sock:
          sock.bind(("127.0.0.1", 0))
          port = sock.getsockname()[1]
      config = pathlib.Path(os.environ["NGINX_" + scenario]).read_text()
      # Only relocate runtime state and the loopback test port. All server
      # roots, exact/SPA routes, aliases, headers and MIME rules are generated
      # by the real NixOS module, rather than reproduced in the test.
      for original, name in [("/run/nginx", "run"), ("/var/log/nginx", "logs"),
                             ("/var/cache/nginx", "cache"), ("/var/spool/nginx", "spool")]:
          config = config.replace(original, str(work / name))
      config = config.replace("127.0.0.1:8080", "127.0.0.1:" + str(port))
      config_path = work / "nginx.conf"
      config_path.write_text(config)
      command = ["nginx", "-e", "stderr", "-p", str(work), "-c", str(config_path)]
      subprocess.run(command + ["-t"], check=True)
      server = subprocess.Popen(command)
      try:
          base = "http://127.0.0.1:" + str(port)
          for _ in range(100):
              if server.poll() is not None:
                  raise RuntimeError("nginx exited before becoming reachable")
              try:
                  if request(base, "/healthz")[0] == 200:
                      break
              except OSError:
                  pass
              time.sleep(0.05)
          else:
              raise RuntimeError("nginx did not start within the bounded deadline")
          for route in ["/", "/index.html", "/propulsion", "/recovery/nested", "/ui-healthz"]:
              status, headers, body = request(base, route)
              assert status == 200 and b"operator-route-fixture" in body, route
          status, headers, body = request(base, "/assets/app.js")
          assert status == 200 and b"bundled-asset" in body
          for route in ["/assets/missing.js", "/tiles/1/2/3.png"]:
              status, _, body = request(base, route)
              assert status == 404 and b"operator-route-fixture" not in body, route
          status, headers, body = request(base, "/station-config.json?refresh=1")
          assert status == 200 and headers.get_content_type() == "application/json"
          assert "no-store" in headers["Cache-Control"]
          assert json.loads(body) == {
              "schemaVersion": 1,
              "fillStationWebSocketUrl": "ws://fill.test/socket",
              "grafanaUrl": None,
              "fieldMode": True,
              "map": {"tileUrl": "/tiles/{z}/{x}/{y}.png", "tilesConfigured": directory_configured},
          }
          assert request(base, "/readyz")[0] == 503
          status, _, body = request(base, "/tiles/0/0/0.png")
          if directory_configured:
              assert status == 200 and body == b"local-tile-fixture"
          else:
              assert status == 404
          print(scenario + ": nginx SPA/assets/tiles/config/liveness/readiness checks passed")
      finally:
          server.terminate()
          try:
              server.wait(timeout=5)
          except subprocess.TimeoutExpired:
              server.kill()
              server.wait(timeout=5)
  PY
  touch "$out"
''
