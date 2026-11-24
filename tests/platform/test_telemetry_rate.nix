{ flake }:
let
  lib = flake.inputs.nixpkgs.lib;
  type = flake.mixosConfigurations.fill-station.options.fillStation.telemetryRateHz.type;
  fifty = (flake.inputs.mixos.lib.mixosSystem {
    modules = [ ../../nix/mixos-configurations/fill-station-hybrid-test.nix
      { _module.args.inputs = flake.inputs // { self = flake; };
        fillStation.telemetryRateHz = 50; } ];
  }).config;
  checks = {
    fiftyHzStartup = lib.hasInfix "FILL_STATION_MQTT_HZ=50 " fifty.init.fill-station.process;
    acceptsTestRates = lib.all type.check [ 1 10 20 25 50 ];
    rejectsInvalidRates = lib.all (value: !type.check value) [ 0 51 (-1) 1.5 "50" ];
    defaultsStayTen = lib.all (name:
      let c = flake.mixosConfigurations.${name}.config;
      in c.fillStation.telemetryRateHz == 10
        && lib.hasInfix "FILL_STATION_MQTT_HZ=10 " c.init.fill-station.process
        && c.init.fill-station.action == "respawn"
    ) [ "fill-station" "fill-station-hybrid-test" "fill-station-liquid" "fill-station-debug" ];
  };
in assert lib.all (value: value) (builtins.attrValues checks); checks
