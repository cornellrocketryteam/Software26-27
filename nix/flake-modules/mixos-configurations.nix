{
  inputs,
  lib,
  ...
}:
let
  configurationsFor = buildSystem: lib.mapAttrs' (
    file: _:
    let
      name = lib.removeSuffix ".nix" file;
    in
    lib.nameValuePair name (
      inputs.mixos.lib.mixosSystem {
        modules = [
          (
            { pkgs, ... }:
            {
              _module.args.inputs = inputs;
              fillStation.buildSystem = lib.mkDefault buildSystem;
              etc."hostname".source = lib.mkDefault (pkgs.writeText "hostname" name);
            }
          )
          ../mixos-configurations/${file}
        ];
      }
    )
  ) (lib.filterAttrs (file: type: type == "regular" && lib.hasSuffix ".nix" file)
    (builtins.readDir ../mixos-configurations));
in
{
  # One configuration per nix/mixos-configurations/<name>.nix
  flake.mixosConfigurations = configurationsFor "aarch64-linux";
  flake.mixosBuildConfigurations = {
    aarch64-linux = configurationsFor "aarch64-linux";
    x86_64-linux = configurationsFor "x86_64-linux";
  };
}
