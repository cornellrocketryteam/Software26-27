{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  inherit (config.fillStation) debug;

  # The one fill-station build used by both init and /bin
  fill-station = pkgs.crt.fill-station.override {
    withHelpers = debug; # ADC CLI tools only in debug
    inherit (config.fillStation) mode;
  };
in
{
  imports = [
    ./fit
    ./options.nix
    ./ospi-image
    ./sd-image
  ];

  # AM64x (Cortex-A53) musl userland, cross-built on aarch64-linux (CI and our remote builder)
  nixpkgs.pkgs = import inputs.nixpkgs {
    localSystem = "aarch64-linux";
    crossSystem = {
      config = "aarch64-unknown-linux-musl";
      gcc.cpu = "cortex-a53";
    };
    overlays = [
      inputs.self.overlays.default
      inputs.mixos.overlays.default
    ];
  };

  boot.kernelPackages = pkgs.linuxPackagesFor pkgs.crt.fill-station-linux;
  boot.firmware = [ pkgs.crt.wl18xx-firmware ];

  state = {
    enable = true;
    fsType = "vfat";
    options = [ "noatime" ];
    source = "/dev/fill-station-state";
    # MixOS mounts the device directly, so resolve the label before mounting.
    init = pkgs.writeScript "fill-station-state-init" ''
      #!/bin/sh
      set -eu
      device=$(findfs LABEL=DATA)
      ln -sf "$device" /dev/fill-station-state
    '';
  };

  init = {
    shell = {
      tty = "ttyS2";
      action = "askfirst";
      process = "/bin/sh";
    };

    sshd = {
      action = "respawn";
      # -R: generate missing host keys; state preserves them.
      # -D: read authorized_keys from /etc/dropbear.
      # -s: disable password login.
      process = "${lib.getExe' pkgs.dropbear "dropbear"} -F -R -s -D /etc/dropbear";
    };

    fill-station = {
      action = "respawn";
      process = lib.getExe fill-station;
    };

    wpa_supplicant = {
      action = "respawn";
      process = "${lib.getExe' pkgs.crt.wpa-supplicant-minimal "wpa_supplicant"} -i wlan0 -c /etc/wpa_supplicant.conf";
    };

    dhcp = {
      action = "respawn";
      process = "${lib.getExe' pkgs.busybox "udhcpc"} -f -i wlan0";
    };
  };

  packages = [
    fill-station
    pkgs.iw
  ]
  ++ lib.optionals debug [
    pkgs.libgpiod
    pkgs.crt.wpa-supplicant-minimal
    pkgs.tcpdump
  ];

  etc."dropbear/authorized_keys" = {
    source = ./authorized_keys;
    mode = "0600";
  };

  etc."wpa_supplicant.conf".source = pkgs.writeText "wpa_supplicant.conf" ''
    network={
      ssid="CornellRocketry-Fill"
      psk="Rocketry2526"
    }
  '';

  users.root = {
    uid = 0;
    gid = 0;
    shell = "/bin/sh";
    home = "/root";
  };
  groups.root.id = 0;
}
