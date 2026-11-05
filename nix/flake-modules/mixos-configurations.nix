{
  inputs,
  self,
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
              nixpkgs.nixpkgs = inputs.nixpkgs;
              nixpkgs.overlays = [
                self.overlays.default
                inputs.mixos.overlays.default
              ];
              etc."hostname".source = lib.mkDefault (pkgs.writeText "hostname" name);
            }
          )
          ../mixos-configurations/${file}
        ];
      }
    )
  ) (builtins.readDir ../mixos-configurations);
}
