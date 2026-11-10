{
  config,
  lib,
  pkgs,
  ...
}:
let
  fill-station = pkgs.crt.fill-station.override {
    inherit (config.fillStation) mode;
    withHelpers = config.fillStation.debug;
  };
in
{
  imports = [ ./fill-station-liquid.nix ];

  # Replace normal startup: this image must not initialize or command actuators.
  init.fill-station.process = lib.mkForce "sh -c 'exec ${lib.getExe fill-station} --ads7128-test 0x10 >/dev/ttyS2 2>&1'";
}
