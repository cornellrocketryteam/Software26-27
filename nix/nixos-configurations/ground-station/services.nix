# Separate from the hardware-tested foundation; activation requires prepared
# runtime credentials. See docs/operations/telemetry-stack.md for acceptance.
{ ... }:
{
  groundStation = {
    telemetry = {
      enable = true;
      secretsFile = "/var/lib/ground-station/telemetry-secrets.json";
      imagePins = builtins.fromJSON (builtins.readFile ./telemetry-images.json);
    };
    grafana.rootUrl = "http://192.168.1.206:8080/grafana/";
  };
}
