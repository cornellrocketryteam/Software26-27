{ lib, ... }:
{
  # Which fill-station Cargo feature is compiled into the image. The plain
  # fill-station configuration defaults to hybrid; fill-station-liquid and
  # fill-station-hybrid set it explicitly. "none" builds with neither feature.
  options.fillStation.mode = lib.mkOption {
    type = lib.types.enum [
      "none"
      "liquid"
      "hybrid"
    ];
    default = "hybrid";
    description = "Fill-station build mode (Cargo feature passed to the fill-station package).";
  };
}
