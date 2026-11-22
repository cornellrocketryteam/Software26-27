# Actual Sway/Chromium display test with two virtual Wayland outputs and no NIC.
# This proves software layout/restart behavior, not UM560 GPU/cable compatibility.
{ pkgs }:
pkgs.testers.runNixOSTest {
  name = "ground-local-dual-display";
  requiredFeatures = { kvm = false; nixos-test = false; };
  node.pkgs = pkgs.lib.mkForce (import pkgs.path { system = "x86_64-linux"; });
  qemu = { package = pkgs.qemu; forceAccel = false; };
  nodes.station = { config, lib, pkgs, ... }: {
    imports = [ ../../nix/nixos-configurations/ground-station ];
    networking.hostName = lib.mkForce "station";
    users.users.root.hashedPasswordFile = lib.mkForce null;
    users.users.operator.uid = 1001;
    groundStation = {
      virtualMachine = true;
      operatorUi.enable = true;
      operatorUi.package = pkgs.writeTextDir "index.html" "<html><body>Operator controls fixture</body></html>";
      kiosk = {
        enable = true;
        # The virtual compositor has CPU-only headless outputs, not the UM560 GPU.
        browserPackage = pkgs.writeShellScriptBin "chromium" ''
          exec ${pkgs.chromium}/bin/chromium --disable-gpu --enable-logging=stderr "$@" 2>>/tmp/display-chromium.log
        '';
      };
      cameras = { enable = true; credentialsFile = "/etc/test-cameras.json"; };
    };
    environment.etc."test-cameras.json".text = builtins.toJSON (lib.genAttrs
      [ "fillcam0" "fillcam1" "fillcam2" ] (_: { username = "synthetic"; password = "synthetic-only"; }));
    services.nginx.virtualHosts.ground-station.locations."/grafana/" = {
      alias = "${pkgs.writeTextDir "index.html" "<html><body style='background:#132735;color:white;font:32px sans-serif'>FillOps display fixture</body></html>"}/";
      index = "index.html";
    };
    services.nginx.virtualHosts.ground-station.locations."= /grafana/api/health" = {
      return = "200 '{\"database\":\"ok\"}'";
      extraConfig = "default_type application/json;";
    };
    systemd.services.greetd.environment = {
      WLR_BACKENDS = "headless";
      WLR_HEADLESS_OUTPUTS = "2";
      WLR_RENDERER = "pixman";
    };
    services.greetd.settings = lib.genAttrs [ "initial_session" "default_session" ] (_: {
      command = lib.mkForce "${pkgs.coreutils}/bin/env WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=2 WLR_RENDERER=pixman ${config.programs.sway.package}/bin/sway --config ${config.system.build.groundStationSwayConfig}";
    });
    virtualisation = {
      memorySize = 4096;
      cores = 4;
      vlans = [ ];
      qemu.networkingOptions = lib.mkForce [ "-nic none" ];
    };
    environment.systemPackages = [ pkgs.jq pkgs.grim pkgs.procps pkgs.util-linux ];
  };
  testScript = ''
    import json
    start_all()
    station.wait_for_unit("nginx.service", timeout=300)
    station.wait_for_unit("greetd.service", timeout=300)
    station.wait_until_succeeds("test -S /run/user/1001/sway-ipc.1001.*.sock", timeout=300)
    socket = station.succeed("printf '%s\\n' /run/user/1001/sway-ipc.1001.*.sock").strip()
    def ipc(command):
        return "runuser -u operator -- swaymsg -s " + socket + " " + command
    def wait_view(view):
        try:
            query = "pid=$(pgrep -u operator -f 'chrom.*--class=crt-" + view + "' | head -1); test -n \"$pid\" && "
            query += ipc("-t get_tree -r") + " | jq -e --argjson pid \"$pid\" '.. | objects | select(.pid? == $pid)'"
            station.wait_until_succeeds(query, timeout=360)
        except Exception:
            print(station.succeed(ipc("-t get_outputs -r")))
            print(station.succeed(ipc("-t get_tree -r")))
            print(station.succeed("journalctl -b -u greetd --no-pager -n 100"))
            print(station.succeed("ps -u operator -o pid,args"))
            print(station.succeed("cat /tmp/display-chromium.log || true"))
            raise
    station.wait_until_succeeds(ipc("-t get_outputs -r"), timeout=120)
    print(station.succeed(ipc("-t get_outputs -r")))
    wait_view("telemetry")
    wait_view("commanding")
    tree = json.loads(station.succeed(ipc("-t get_tree -r")))
    def window_pids(node):
        result = [node.get("pid")]
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            result += window_pids(child)
        return result
    outputs = [n for n in tree["nodes"] if n.get("type") == "output"]
    telemetry_pid = int(station.succeed("pgrep -u operator -f 'chrom.*--class=crt-telemetry' | head -1").strip())
    commanding_pid = int(station.succeed("pgrep -u operator -f 'chrom.*--class=crt-commanding' | head -1").strip())
    station.wait_until_succeeds(ipc("-t get_tree -r") + " | jq -e '.. | objects | select(.name? == \"telemetry\") | .. | objects | select(.pid? == " + str(telemetry_pid) + ")'", timeout=60)
    tree = json.loads(station.succeed(ipc("-t get_tree -r")))
    outputs = [n for n in tree["nodes"] if n.get("type") == "output"]
    assert any(telemetry_pid in window_pids(o) for o in outputs)
    assert any(commanding_pid in window_pids(o) for o in outputs)
    assert not any(telemetry_pid in window_pids(o) and commanding_pid in window_pids(o) for o in outputs)
    station.succeed(ipc("output HEADLESS-2 disable"))
    wait_view("overview")
    station.succeed(ipc("output HEADLESS-2 enable"))
    wait_view("telemetry")
    wait_view("commanding")
    original = station.succeed("pgrep -u operator -f 'chrom.*--class=crt-telemetry' | head -1").strip()
    station.succeed("pkill -u operator -f 'chrom.*--class=crt-telemetry'")
    station.wait_until_succeeds("test \"$(pgrep -u operator -f 'chrom.*--class=crt-telemetry' | head -1)\" != \"" + original + "\" && pgrep -u operator -f 'chrom.*--class=crt-telemetry'", timeout=120)
    wait_view("telemetry")
    station.succeed("test -z \"$(find /sys/class/net -mindepth 1 -maxdepth 1 ! -name lo -print -quit)\"")
    station.succeed("systemctl restart greetd")
    # Socket files can outlive the old compositor. Select a responding NEW
    # session instead of requiring old filesystem entries to be removed.
    discover = "for candidate in /run/user/1001/sway-ipc.1001.*.sock; do "
    discover += "if test \"$candidate\" != " + socket + " && runuser -u operator -- swaymsg -s \"$candidate\" -t get_outputs -r >/dev/null 2>&1; then "
    discover += "printf '%s\\n' \"$candidate\"; exit 0; fi; done; exit 1"
    station.wait_until_succeeds(discover, timeout=120)
    socket = station.succeed(discover).strip()
    wait_view("telemetry")
    wait_view("commanding")
  '';
}
