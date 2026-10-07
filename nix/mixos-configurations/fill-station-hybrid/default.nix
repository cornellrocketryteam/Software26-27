{ lib, pkgs, ... }:

{
  imports = [ ../fill-station ];

  # Override the fill-station package to compile with the hybrid feature
  nixpkgs.overlays = [
    (final: prev: {
      crt = prev.crt // {
        fill-station = prev.crt.fill-station.override { mode = "hybrid"; };
      };
    })
  ];
}
