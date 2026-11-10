{ lib, pkgs, ... }:
{
  imports = [
    ../../nixos-modules/ground-station
    ./hardware.nix
  ];

  # The flake constructor selects x86_64-linux. Don't redefine hostPlatform:
  # runNixOSTest supplies an already instantiated, read-only package set.
  assertions = [ {
    assertion = pkgs.stdenv.hostPlatform.system == "x86_64-linux";
    message = "ground-station requires x86_64-linux; select the matching NixOS package platform.";
  } ];
  networking.hostName = lib.mkDefault "ground-station";
  system.stateVersion = "26.11";
}
