{ flake }:
let
  lib = flake.inputs.nixpkgs.lib;
  check = system: name: operating:
    let
      c = flake.mixosBuildConfigurations.${system}.${name}.config;
      p = c.nixpkgs.pkgs;
      app = p.crt.fill-station.override { mode = c.fillStation.mode; operatingProfile = operating; };
      dt = p.crt.fillstation-dtbo.override { profile = c.fillStation.mode; operatingProfile = operating; };
      pru = p.crt.fill-station-pru.override { profile = c.fillStation.mode; operatingProfile = operating; };
    in assert c.fillStation.operatingProfile == operating;
       assert app.FILL_STATION_OPERATING_PROFILE == (if operating == null then "" else operating);
       assert c.system.build.pinmuxOverlay.drvPath == dt.drvPath;
       assert lib.hasInfix (if operating == null then "--profile liquid" else "--operating-profile ${operating}") dt.buildPhase;
       assert lib.hasInfix (if operating == null then "--profile liquid" else "--operating-profile ${operating}") pru.buildPhase;
       assert c.system.build.ospiImage.system == system;
       { inherit operating; image = c.system.build.ospiImage.drvPath; };
in lib.genAttrs [ "aarch64-linux" "x86_64-linux" ] (system: {
  hybrid = check system "fill-station" "hybrid";
  hybrid-test = check system "fill-station-hybrid-test" "hybrid-test";
  liquid = check system "fill-station-liquid" null;
})
