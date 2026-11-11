# Explicit/manual real-service acceptance. No physical host activation or NICs.
# Host pkgs may be aarch64-darwin/linux; guest and service images stay x86_64.
{ pkgs }:
pkgs.testers.runNixOSTest {
  name = "ground-telemetry-offline-recovery";
  requiredFeatures = { kvm = false; nixos-test = false; apple-virt = false; };
  node.pkgs = pkgs.lib.mkForce (import pkgs.path { system = "x86_64-linux"; });
  qemu = { package = pkgs.qemu; forceAccel = false; };
  nodes.station = { config, lib, pkgs, ... }:
  let
    helper = pkgs.callPackage ../../nix/packages/crt/ground-telemetry/package.nix { };
    # Same test-only normalization as the UI VM for a Mac-shared Nix store.
    terminfo = pkgs.runCommand "telemetry-vm-terminfo" { } ''
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
    fixture = pkgs.writeText "ground-telemetry-vm-fixture.py" ''
      import importlib.util
      import json
      import os
      from pathlib import Path
      import secrets
      import shutil
      import sys
      sys.dont_write_bytecode = True
      source = "${helper}/libexec/ground-telemetry.py"
      spec = importlib.util.spec_from_file_location("runtime", source)
      runtime = importlib.util.module_from_spec(spec)
      spec.loader.exec_module(runtime)
      state = Path("/var/lib/ground-telemetry-vm")
      private = state / "secrets.json"
      if not private.exists():
          fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
          with os.fdopen(fd, "w") as stream:
              json.dump({key: secrets.token_urlsafe(32) for key in runtime.SECRET_KEYS}, stream)
              stream.flush()
              os.fsync(stream.fileno())
      output = Path("/run/ground-telemetry-vm")
      shutil.copyfile(private, output / "secrets.json")
      (output / "secrets.json").chmod(0o600)
      shutil.copyfile(source, output / "runtime.py")
      link = output / "assets"
      if link.is_symlink():
          link.unlink()
      link.symlink_to("${helper}/share/ground-telemetry", target_is_directory=True)
    '';
    check = pkgs.writeShellScriptBin "ground-telemetry-vm-check" ''
      exec ${pkgs.python3}/bin/python3 ${./telemetry_vm_check.py} \
        --stack-source ${./telemetry_stack_integration.py} \
        --docker ${config.virtualisation.docker.package}/bin/docker "$@"
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
      telemetry = {
        enable = true;
        secretsFile = "/var/lib/ground-telemetry-vm/secrets.json";
        imagePins = builtins.fromJSON (builtins.readFile ./telemetry_nix_pins.json);
      };
    };
    virtualisation = {
      # The runner also needs memory/workspace beyond this guest allocation.
      # This is a fixture budget, not the physical station's hardware profile.
      memorySize = 3072;
      cores = 2;
      diskSize = 16384;
      vlans = [ ];
      qemu.networkingOptions = lib.mkForce [ "-nic none" ];
      # These services use host networking; no unused Docker bridge is needed.
      docker.daemon.settings = { bridge = "none"; iptables = false; ip6tables = false; };
    };
    environment.systemPackages = [ pkgs.curl pkgs.python3 check ];
    systemd.tmpfiles.rules = [ "d /var/lib/ground-telemetry-vm 0700 root root - -" ];
    systemd.services.ground-telemetry-vm-fixture = {
      wantedBy = [ "multi-user.target" ];
      before = [ "ground-telemetry-prepare.service" ];
      unitConfig.ConditionPathExists = "/var/lib/ground-telemetry-vm/allow-credentials";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        UMask = "0077";
        RuntimeDirectory = "ground-telemetry-vm";
        RuntimeDirectoryMode = "0700";
        ExecStart = "${pkgs.python3}/bin/python3 ${fixture}";
      };
    };
    systemd.services.ground-telemetry-prepare = {
      requires = [ "ground-telemetry-vm-fixture.service" ];
      after = [ "ground-telemetry-vm-fixture.service" ];
    };
    # Hold the probe timer out of the recovery window. Its Requires edges can
    # otherwise start Grafana/migration/DB and mask a missing recovery edge.
    systemd.timers.ground-telemetry-grafana-ready.wantedBy = lib.mkForce [ ];
    systemd.services.ground-telemetry-database.serviceConfig.ExecStartPre = [
      (pkgs.writeShellScript "fail-first-telemetry-migration" ''
        if ! test -e /var/lib/ground-telemetry-vm/migration-failed-once; then
          ${pkgs.coreutils}/bin/touch /var/lib/ground-telemetry-vm/migration-failed-once
          exit 1
        fi
      '')
    ];
  };
  testScript = ''
    import time

    def check_network():
        station.succeed("test -z \"$(find /sys/class/net -mindepth 1 -maxdepth 1 ! -name lo -print -quit)\"")
        station.succeed("test $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/readyz) = 503")

    def wait_stack():
        deadline = time.monotonic() + 900
        next_health = 0.0
        units = ["ground-telemetry-prepare", "ground-telemetry-database", "ground-telemetry-broker",
                 "docker-ground-timescaledb", "docker-ground-emqx", "docker-ground-grafana"]
        while time.monotonic() < deadline:
            if time.monotonic() >= next_health:
                from pathlib import Path
                if Path("/proc/meminfo").exists():
                    memory = [line for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:")]
                    oom = [line for line in Path("/proc/vmstat").read_text().splitlines() if line.startswith("oom_kill ")]
                    print("Test-host health:", memory, oom)
                next_health = time.monotonic() + 30
            try:
                nif_failure, _ = station.execute("journalctl -b -u docker-ground-emqx.service --no-pager | grep -q nif_library_not_loaded")
                active = all(station.execute("systemctl is-active --quiet " + unit)[0] == 0 for unit in units)
            except BrokenPipeError:
                import os
                from pathlib import Path
                if Path("/proc/vmstat").exists():
                    print("Test-host failure counters:", [line for line in Path("/proc/vmstat").read_text().splitlines() if line.startswith("oom_kill ")])
                events = Path("/sys/fs/cgroup/memory.events")
                if events.exists():
                    print("Test-host cgroup memory events:", events.read_text())
                process = station.process
                if process is not None:
                    print("VM launcher exit:", process.poll())
                    if process.stdout is not None:
                        os.set_blocking(process.stdout.fileno(), False)
                        print(process.stdout.read(8192))
                raise
            assert nif_failure != 0, "The amd64 EMQX native library failed in the full x86 guest."
            if active:
                station.succeed("ground-telemetry-vm-check inventory")
                station.succeed("ground-telemetry-vm-check grafana")
                return
            time.sleep(3)
        raise RuntimeError("Automatic telemetry startup/recovery exceeded its deadline.")

    start_all()
    station.wait_for_unit("nginx.service", timeout=600)
    try:
        station.wait_for_unit("multi-user.target", timeout=120)
    except Exception:
        print(station.succeed("systemctl list-jobs --no-pager"))
        print(station.succeed("systemctl show multi-user.target ground-telemetry-prepare.service -p ActiveState -p SubState -p After -p Before"))
        raise
    check_network()
    station.succeed("curl --fail http://127.0.0.1:8080/ui-healthz | grep 'id=\"root\"'")
    station.succeed("curl --fail http://127.0.0.1:8080/station-config.json | grep '\"fillStationWebSocketUrl\":null'")
    station.fail("test -f /var/lib/ground-telemetry-vm/secrets.json")
    station.wait_until_succeeds("test $(systemctl show ground-telemetry-prepare -p NRestarts --value) -gt 0", timeout=120)
    station.fail("systemctl is-active --quiet ground-telemetry-broker")
    station.fail("systemctl is-active --quiet ground-telemetry-grafana-ready.timer")

    # Release only the fixture input. The production units must recover through
    # their own retries/dependency edges, with no manual container/unit start.
    station.succeed("touch /var/lib/ground-telemetry-vm/allow-credentials")
    station.succeed("systemctl start ground-telemetry-vm-fixture")
    wait_stack()
    station.succeed("test -f /var/lib/ground-telemetry-vm/migration-failed-once")
    station.succeed("test $(systemctl show ground-telemetry-database -p NRestarts --value) -gt 0")
    station.succeed("ground-telemetry-vm-check publish --cycles 1")
    station.wait_until_succeeds("ground-telemetry-vm-check rows --cycles 1", timeout=120)

    for container, provision in [("ground-timescaledb", "ground-telemetry-database"),
                                 ("ground-emqx", "ground-telemetry-broker")]:
        old = station.succeed("systemctl show " + provision + " -p InvocationID --value").strip()
        old_broker = station.succeed("systemctl show ground-telemetry-broker -p InvocationID --value").strip()
        old_container = station.succeed("docker inspect --format '{{.Id}}' " + container).strip()
        restarts = station.succeed("systemctl show docker-" + container + " -p NRestarts --value").strip()
        station.succeed("docker kill --signal KILL " + container)
        station.wait_until_succeeds("test $(systemctl show docker-" + container + " -p NRestarts --value) -gt " + restarts, timeout=300)
        wait_stack()
        assert station.succeed("docker inspect --format '{{.Id}}' " + container).strip() != old_container
        assert station.succeed("systemctl show " + provision + " -p InvocationID --value").strip() != old
        assert station.succeed("systemctl show ground-telemetry-broker -p InvocationID --value").strip() != old_broker
        station.succeed("ground-telemetry-vm-check rows --cycles 1")

    old_grafana = station.succeed("docker inspect --format '{{.Id}}' ground-grafana").strip()
    restarts = station.succeed("systemctl show docker-ground-grafana -p NRestarts --value").strip()
    station.succeed("docker kill --signal KILL ground-grafana")
    station.wait_until_succeeds("test $(systemctl show docker-ground-grafana -p NRestarts --value) -gt " + restarts, timeout=300)
    station.wait_until_succeeds("ground-telemetry-vm-check grafana", timeout=300)
    assert station.succeed("docker inspect --format '{{.Id}}' ground-grafana").strip() != old_grafana
    station.succeed("ground-telemetry-vm-check publish --cycles 2")
    station.wait_until_succeeds("ground-telemetry-vm-check rows --cycles 2", timeout=120)
    station.succeed("cp --preserve=mode /var/lib/ground-telemetry-vm/secrets.json /var/lib/ground-telemetry-vm/before-reboot.json")
    old_boot = station.succeed("cat /proc/sys/kernel/random/boot_id").strip()
    station.shutdown()
    station.start()
    station.wait_for_unit("multi-user.target", timeout=600)
    station.wait_for_unit("nginx.service", timeout=120)
    check_network()
    wait_stack()
    assert station.succeed("cat /proc/sys/kernel/random/boot_id").strip() != old_boot
    station.succeed("cmp -s /var/lib/ground-telemetry-vm/secrets.json /var/lib/ground-telemetry-vm/before-reboot.json")
    station.succeed("ground-telemetry-vm-check rows --cycles 2")
    station.succeed("ground-telemetry-vm-check publish --cycles 3")
    station.wait_until_succeeds("ground-telemetry-vm-check rows --cycles 3", timeout=120)
    station.succeed("systemctl start ground-telemetry-grafana-ready.timer")
    station.wait_until_succeeds("test $(systemctl show ground-telemetry-grafana-ready -p ExecMainStartTimestampMonotonic --value) -gt 0", timeout=120)
    station.wait_until_succeeds("test $(systemctl show ground-telemetry-grafana-ready -p SubState --value) = dead", timeout=120)
    station.succeed("test $(systemctl show ground-telemetry-grafana-ready -p Result --value) = success")
    station.fail("test -e /etc/systemd/system/ground-command-listener.service")
  '';
}
