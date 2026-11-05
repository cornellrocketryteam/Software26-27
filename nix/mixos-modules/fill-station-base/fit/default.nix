{ config, pkgs, ... }:
let
  pinmux = pkgs.crt.fillstation-dtbo.override { profile = config.fillStation.mode; };
in
{
  system.build.pinmuxOverlay = pinmux;

  system.build.fitImage = pkgs.callPackage ./build-fit-image.nix {
    kernel = "${config.boot.kernel}/Image";
    dtb = "${config.boot.kernel}/dtbs/ti/k3-am642-sk.dtb";
    dtbOverlay = "${pinmux}/k3-am64-fillstation-pinmux-overlay.dtbo";
    pinmuxExpectations = "${pinmux}/expectations.json";
    pinmuxVerifier = "${pinmux}/verify-merged.py";
    initrd = "${config.system.build.initrd}/initrd";
  };
}
