{ flake }:
let
  lib = flake.inputs.nixpkgs.lib;
  select = import ../../nix/mixos-modules/fill-station-base/pru-pwm/select-cores.nix;
  device = enabled: functions: { inherit enabled; connections = lib.imap0
    (index: function: { inherit function; }) functions; };
  profile = connections: { devices = connections; };
  baseline = name:
    let c = flake.mixosConfigurations.${name}.config;
    in assert lib.assertMsg (builtins.all (package: !(lib.hasPrefix "fill-station-pru" (lib.getName package))) c.boot.firmware) "ePWM-only images must not add PRU firmware";
       assert lib.assertMsg (!(lib.hasInfix "pru-start" c.init.fill-station.process)) "ePWM-only startup must remain unchanged";
       { process = c.init.fill-station.process; modules = c.boot.kernelModules; };
in
assert select (profile [ ]) == [ ];
assert select (profile [{ enabled = true; connections.pwm.function = "EHRPWM4_B"; }]) == [ ];
assert select (profile [{ enabled = false; connections.pwm.function = "PRG0_PRU0_GPO2"; }]) == [ ];
assert select (profile [{ enabled = true; connections.pwm.function = "PRG0_PRU1_GPO2"; }]) == [ 1 ];
assert select (profile [
  { enabled = true; connections.pwm.function = "PRG0_PRU1_GPO2"; }
  { enabled = true; connections.pwm.function = "PRG0_PRU0_GPO19"; }
]) == [ 0 1 ];
lib.genAttrs [ "fill-station" "fill-station-liquid" "fill-station-debug" ] baseline
