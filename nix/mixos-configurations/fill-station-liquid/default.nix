{ lib, pkgs, ... }:

{
  imports = [ ../fill-station ];

  # Override the process to specifically run in liquid mode
  init.fill-station.process = lib.mkForce "${lib.getExe pkgs.crt.fill-station} --liquid";
}
