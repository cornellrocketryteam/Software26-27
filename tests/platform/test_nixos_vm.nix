# Evaluation/build target only in this increment; parent owns authorizing a run.
{ pkgs }:
pkgs.testers.runNixOSTest {
  name = "ground-station-foundation";
  nodes.station = { lib, ... }: {
    imports = [ ../../nix/nixos-configurations/ground-station ];
    networking.hostName = lib.mkForce "station";
    # The test harness injects a password file; retain the profile's locked root
    # account without competing password mechanisms. Driver uses its backdoor.
    users.users.root.hashedPasswordFile = lib.mkForce null;
    groundStation.virtualMachine = true;
    virtualisation.memorySize = 2048;
    environment.systemPackages = [ pkgs.curl ];
  };
  testScript = ''
    start_all()
    station.wait_for_unit("multi-user.target")
    station.wait_for_unit("nginx.service")
    station.succeed("curl --fail http://127.0.0.1:8080/healthz")
    station.succeed("curl --fail http://127.0.0.1:8080/ | grep 'Ground station not provisioned'")
    station.succeed("test $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/readyz) = 503")
    station.succeed("test ! -e /etc/systemd/system/harmonia.socket")
    station.succeed("test ! -e /etc/systemd/system/ground-command-listener.service")
    station.succeed("grep -q 'max-jobs = 0' /etc/nix/nix.conf")
    station.fail("systemctl is-active grafana.service")
    station.fail("systemctl is-active docker.service")
  '';
}
