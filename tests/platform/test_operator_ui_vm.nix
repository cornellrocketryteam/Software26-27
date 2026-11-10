# Explicit/manual VM startup acceptance. Software emulation permits a Linux host
# without KVM; do not add this slower boot check to branch-push image workflows.
{ pkgs }:
pkgs.testers.runNixOSTest {
  name = "ground-operator-ui-startup";
  requiredFeatures = { kvm = false; nixos-test = false; };
  node.pkgs = pkgs.lib.mkForce (import pkgs.path { system = "x86_64-linux"; });
  qemu = { package = pkgs.qemu; forceAccel = false; };
  nodes.station = { lib, pkgs, ... }:
  let
    # Restore only the four console entries used by the initrd to collision-free
    # paths. A Linux store shared from case-insensitive macOS may case-escape
    # ncurses' L/l and V/v directories; physical NixOS configuration is unchanged.
    terminfo = pkgs.runCommand "operator-vm-terminfo" { } ''
      root=${pkgs.ncurses}/share/terminfo
      for entry in l/linux v/vt100 v/vt102 v/vt220; do
        directory="''${entry%/*}"
        name="''${entry#*/}"
        source=
        for candidate in "$root/$entry" "$root/$directory"~nix~case~hack~*/"$name"; do
          if test -f "$candidate"; then source="$candidate"; break; fi
        done
        test -n "$source"
        mkdir -p "$out/$directory"
        cp "$source" "$out/$entry"
      done
    '';
  in {
    imports = [ ../../nix/nixos-configurations/ground-station ];
    networking.hostName = lib.mkForce "station";
    users.users.root.hashedPasswordFile = lib.mkForce null;
    boot.initrd.systemd.contents = lib.genAttrs
      [ "/etc/terminfo/l/linux" "/etc/terminfo/v/vt100" "/etc/terminfo/v/vt102" "/etc/terminfo/v/vt220" ]
      (target: { source = lib.mkForce "${terminfo}/${lib.removePrefix "/etc/terminfo/" target}"; });
    groundStation = {
      virtualMachine = true;
      operatorUi.enable = true;
    };
    virtualisation.memorySize = 1024;
    # Startup acceptance must not borrow internet or a fill-station connection.
    # The test driver uses its serial backdoor; HTTP checks use loopback only.
    virtualisation.vlans = [ ];
    virtualisation.qemu.networkingOptions = lib.mkForce [ "-nic none" ];
    # The VM runner already emits -machine accel=kvm:tcg; do not add a
    # conflicting -accel flag. forceAccel=false permits its software fallback.
    environment.systemPackages = [ pkgs.curl ];
  };
  testScript = ''
    import os
    import time

    try:
        start_all()
    except Exception:
        time.sleep(0.5)
        process = station.process
        if process is not None:
            print(f"VM launcher exit status: {process.poll()}")
            if process.stdout is not None:
                os.set_blocking(process.stdout.fileno(), False)
                print(process.stdout.read(32768))
        raise
    station.wait_for_unit("multi-user.target", timeout=600)
    station.wait_for_unit("nginx.service", timeout=120)
    station.succeed("test -z \"$(find /sys/class/net -mindepth 1 -maxdepth 1 ! -name lo -print -quit)\"")
    station.succeed("curl --fail http://127.0.0.1:8080/healthz")
    station.succeed("curl --fail http://127.0.0.1:8080/ui-healthz | grep 'id=\"root\"'")
    station.succeed("curl --fail http://127.0.0.1:8080/recovery | grep 'id=\"root\"'")
    station.succeed("curl --fail http://127.0.0.1:8080/station-config.json | grep '\"fillStationWebSocketUrl\":null'")
    station.succeed("test $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/readyz) = 503")
    station.succeed("test $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/assets/missing.js) = 404")
    station.succeed("test ! -e /etc/systemd/system/ground-command-listener.service")
    station.fail("systemctl is-active grafana.service")
    station.fail("systemctl is-active docker.service")
  '';
}
