# Scheduling acceptance only: real module dependencies, controlled executables.
# The separate real-image VM remains the ingestion/persistence acceptance test.
{ pkgs }:
(import ./test_telemetry_vm.nix { inherit pkgs; }).extend {
  modules = [ ({ lib, ... }: {
    name = lib.mkForce "ground-telemetry-retry-cadence";
    nodes.station = { lib, pkgs, ... }:
    let
      record = pkgs.writeText "telemetry-attempt.py" ''
        import json
        from pathlib import Path
        import sys
        import time
        root = Path("/var/lib/ground-telemetry-rate")
        name = sys.argv[1]
        with (root / (name + ".jsonl")).open("a") as stream:
            stream.write(json.dumps(time.monotonic()) + "\n")
        raise SystemExit(0 if (root / ("allow-" + name)).exists() else 1)
      '';
      attempt = name: "${pkgs.python3}/bin/python3 ${record} ${name}";
      inert = {
        script = lib.mkForce "exec ${pkgs.coreutils}/bin/sleep infinity";
        preStop = lib.mkForce "";
        postStop = lib.mkForce "";
        serviceConfig = {
          ExecStartPre = lib.mkForce [ ];
          EnvironmentFile = lib.mkForce [ ];
          Type = lib.mkForce "simple";
        };
      };
    in {
      virtualisation.memorySize = lib.mkForce 768;
      # Exercise the normal probe during degraded boot, then withhold it while
      # testing recovery so it cannot conceal a missing success hook.
      systemd.timers.ground-telemetry-grafana-ready.wantedBy = lib.mkOverride 40 [ "timers.target" ];
      virtualisation.oci-containers.containers = lib.genAttrs
        [ "ground-timescaledb" "ground-emqx" "ground-grafana" ]
        (_: { imageFile = lib.mkForce null; environmentFiles = lib.mkForce [ ]; });
      systemd.tmpfiles.rules = [ "d /var/lib/ground-telemetry-rate 0700 root root - -" ];
      systemd.services = {
        docker-ground-timescaledb = inert;
        docker-ground-emqx = inert;
        docker-ground-grafana = inert;
        ground-telemetry-prepare.serviceConfig.ExecStart = lib.mkForce (attempt "prepare");
        ground-telemetry-database.serviceConfig = {
          ExecStartPre = lib.mkForce [ ];
          ExecStart = lib.mkForce (attempt "migration");
        };
        ground-telemetry-broker.serviceConfig.ExecStart = lib.mkForce (attempt "broker");
        ground-telemetry-grafana-ready.serviceConfig.ExecStart = lib.mkForce "${pkgs.coreutils}/bin/true";
      };
    };
    testScript = lib.mkForce ''
      import json

      units = ["ground-telemetry-prepare", "ground-telemetry-database", "ground-telemetry-broker",
               "docker-ground-timescaledb", "docker-ground-emqx", "docker-ground-grafana"]

      def samples(name):
          return [json.loads(line) for line in station.succeed(
              "cat /var/lib/ground-telemetry-rate/" + name + ".jsonl").splitlines()]

      def delayed(name):
          station.wait_until_succeeds("test $(wc -l < /var/lib/ground-telemetry-rate/" + name + ".jsonl) -ge 3", timeout=90)
          values = samples(name)
          gaps = [b - a for a, b in zip(values, values[1:])]
          print(name + " automatic retry gaps:", gaps)
          assert gaps and min(gaps) >= 4.8, name + " bypassed the automatic restart delay"

      def all_active():
          for unit in units:
              station.wait_for_unit(unit + ".service", timeout=90)

      start_all()
      station.wait_for_unit("multi-user.target", timeout=600)
      station.succeed("systemctl is-active --quiet ground-telemetry-grafana-ready.timer")
      delayed("prepare")
      # systemctl formats timer timestamps as durations; D-Bus exposes raw usec.
      triggered = station.succeed("busctl --system get-property org.freedesktop.systemd1 "
          "/org/freedesktop/systemd1/unit/ground_2dtelemetry_2dgrafana_2dready_2etimer "
          "org.freedesktop.systemd1.Timer LastTriggerUSecMonotonic")
      assert int(triggered.split()[1]) > 0
      station.succeed("test $(systemctl show ground-telemetry-grafana-ready -p ExecMainStartTimestampMonotonic --value) = 0")
      station.succeed("systemctl stop ground-telemetry-grafana-ready.timer")
      station.succeed("touch /var/lib/ground-telemetry-rate/allow-prepare")
      station.wait_for_unit("ground-telemetry-prepare", timeout=90)
      prepare_count = len(samples("prepare"))
      delayed("migration")
      assert len(samples("prepare")) == prepare_count, "A failed consumer restarted preparation"
      station.succeed("touch /var/lib/ground-telemetry-rate/allow-migration")
      station.wait_for_unit("ground-telemetry-database", timeout=90)
      migration_count = len(samples("migration"))
      delayed("broker")
      assert len(samples("migration")) == migration_count, "A failed broker restarted migration"
      station.succeed("touch /var/lib/ground-telemetry-rate/allow-broker")
      all_active()

      for container, provision in [("docker-ground-timescaledb", "ground-telemetry-database"),
                                   ("docker-ground-emqx", "ground-telemetry-broker")]:
          old = station.succeed("systemctl show " + provision + " -p InvocationID --value").strip()
          old_broker = station.succeed("systemctl show ground-telemetry-broker -p InvocationID --value").strip()
          station.succeed("systemctl kill --kill-whom=main --signal=KILL " + container)
          station.wait_until_succeeds("test $(systemctl show " + container + " -p NRestarts --value) -gt 0", timeout=90)
          all_active()
          assert station.succeed("systemctl show " + provision + " -p InvocationID --value").strip() != old
          assert station.succeed("systemctl show ground-telemetry-broker -p InvocationID --value").strip() != old_broker

      station.succeed("systemctl kill --kill-whom=main --signal=KILL docker-ground-grafana")
      station.wait_until_succeeds("test $(systemctl show docker-ground-grafana -p NRestarts --value) -gt 0", timeout=90)
      all_active()
      station.succeed("systemctl start ground-telemetry-grafana-ready.timer")
      station.wait_until_succeeds("test $(systemctl show ground-telemetry-grafana-ready -p ExecMainStartTimestampMonotonic --value) -gt 0", timeout=90)
      station.succeed("test -z \"$(find /sys/class/net -mindepth 1 -maxdepth 1 ! -name lo -print -quit)\"")
      station.succeed("test $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/readyz) = 503")
    '';
  }) ];
}
