{ flake }:
let
  lib=flake.inputs.nixpkgs.lib;
  station=flake.nixosConfigurations.ground-station.config;
  contributor=../../nix/mixos-modules/fill-station-base/authorized_keys;
  deployment=../../nix/mixos-modules/fill-station-base/deployment_authorized_keys;
  check=name: let c=flake.mixosConfigurations.${name}.config; in
    assert lib.hasInfix (builtins.readFile contributor) c.etc."dropbear/authorized_keys".source.text;
    assert lib.hasInfix (builtins.readFile deployment) c.etc."dropbear/authorized_keys".source.text;
    assert c.etc."dropbear/authorized_keys".mode=="0600"; true;
in
assert builtins.pathExists deployment;
assert map builtins.baseNameOf station.users.users.ground-admin.openssh.authorizedKeys.keyFiles==["authorized_keys"];
assert map builtins.readFile station.users.users.ground-admin.openssh.authorizedKeys.keyFiles==[(builtins.readFile contributor)];
lib.genAttrs ["fill-station" "fill-station-hybrid-test" "fill-station-liquid"] check
