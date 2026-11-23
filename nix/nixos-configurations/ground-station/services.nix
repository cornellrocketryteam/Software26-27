# Separate from the hardware-tested foundation; activation requires prepared
# runtime credentials. See docs/operations/telemetry-stack.md for acceptance.
{ config, pkgs, ... }:
{
  environment.systemPackages = [ (pkgs.callPackage ../../packages/crt/platform-cli/package.nix {
    nix = config.nix.package;
  }) ];
  groundStation = {
    timeServer.enable = true;
    kiosk.enable = true;
    networkDevices.enable = true;
    operatorUi.fillStationWebSocketUrl = "ws://192.168.1.106:9000";
    cameras = {
      enable = true;
      credentialsFile = "/var/lib/ground-station/cameras/credentials.json";
    };
    telemetry = {
      enable = true;
      secretsFile = "/var/lib/ground-station/telemetry-secrets.json";
      imagePins = builtins.fromJSON (builtins.readFile ./telemetry-images.json);
    };
    grafana.rootUrl = "http://192.168.1.206:8080/grafana/";
  };
}
