{
  inputs,
  lib,
  ...
}:
{
  # One configuration per nix/mixos-configurations/<name>.nix
  flake.mixosConfigurations = lib.mapAttrs' (
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
              # Each machine module sets its own nixpkgs.pkgs (target platform) from inputs
              _module.args.inputs = inputs;
              etc."hostname".source = lib.mkDefault (pkgs.writeText "hostname" name);
            }
          )
          ../mixos-configurations/${file}
        ];
      }
    )
  ) (builtins.readDir ../mixos-configurations);
}
