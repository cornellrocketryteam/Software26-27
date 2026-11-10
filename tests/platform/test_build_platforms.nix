{ flake }:
let
  lib = flake.inputs.nixpkgs.lib;
  machines = {
    fill-station = "hybrid";
    fill-station-liquid = "liquid";
  };
  check = buildSystem: name: mode:
    let c = flake.mixosBuildConfigurations.${buildSystem}.${name}.config;
    in
    assert lib.assertMsg (c.nixpkgs.pkgs.stdenv.buildPlatform.system == buildSystem)
      "wrong build platform for ${name}";
    assert lib.assertMsg (c.nixpkgs.pkgs.stdenv.hostPlatform.config == "aarch64-unknown-linux-musl")
      "cross-build changed the board target";
    assert lib.assertMsg (c.fillStation.mode == mode && c.state.fsType == "ext4")
      "cross-build changed vehicle or persistent-state policy";
    assert lib.assertMsg (c.system.build.sdImage.system == buildSystem
      && c.system.build.fitImage.system == buildSystem
      && c.system.build.pinmuxOverlay.system == buildSystem)
      "image components require a different worker";
    { inherit buildSystem mode; image = c.system.build.sdImage.drvPath; };
  results = lib.genAttrs [ "aarch64-linux" "x86_64-linux" ]
    (system: lib.mapAttrs (check system) machines);
in
assert lib.assertMsg (builtins.all
  (name: flake.mixosConfigurations.${name}.config.system.build.sdImage.drvPath
    == flake.mixosBuildConfigurations.aarch64-linux.${name}.config.system.build.sdImage.drvPath)
  (builtins.attrNames machines)) "default ARM64 build interface changed";
results
