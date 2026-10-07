{ lib, pkgs, ... }:

{
  imports = [ ../fill-station ];

  # Override the process to specifically run in hybrid mode
  init.fill-station.process = lib.mkForce "${lib.getExe pkgs.crt.fill-station} --hybrid";
}
