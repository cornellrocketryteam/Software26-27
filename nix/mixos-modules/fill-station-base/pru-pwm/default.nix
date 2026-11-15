{ config, lib, pkgs, ... }:
let
  profile = builtins.fromJSON (builtins.readFile ../../../../fill-station/hardware/profiles/${config.fillStation.mode}.json);
  cores = if config.fillStation.mode == "none" then [ ] else import ./select-cores.nix profile;
  firmware = pkgs.crt.fill-station-pru.override { profile = config.fillStation.mode; };
  application = pkgs.crt.fill-station.override {
    withHelpers = config.fillStation.debug;
    inherit (config.fillStation) mode;
  };
  startup = pkgs.writeShellScript "fill-station-pru-start" ''
    exec ${lib.getExe' pkgs.busybox "sh"} ${./start.sh} /sys ${lib.escapeShellArg (lib.concatMapStringsSep " " toString cores)} ${lib.getExe application}
  '';
in
lib.mkIf (cores != [ ]) {
  boot.firmware = [ firmware ];
  boot.kernelModules = [ "pruss" "irq-pruss-intc" "pru_rproc" "rpmsg_ctrl" "rpmsg_char" ];
  init.fill-station.process = lib.mkForce (toString startup);
}
