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
    inherit (config.fillStation) mode extraFeatures;
  };
in
{
  imports = [
    ./fit
    ./options.nix
    ./ospi-image
    ./sd-image
  ];

  # Keep the tested ARM64 builder default; explicit variants can cross-build
  # from the x86 ground station without changing the board's target platform.
  nixpkgs.pkgs = import inputs.nixpkgs {
    localSystem = config.fillStation.buildSystem;
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
    # MixOS uses this filesystem for OverlayFS upper/work directories in /etc.
    fsType = "ext4";
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
      # MixOS mounts / as tmpfs with mode 1777. Dropbear checks every parent
      # of authorized_keys and rejects a group/world-writable /, even with
      # the sticky bit. Correct it before starting the SSH server.
      process = "sh -c 'chmod 0755 / && exec ${lib.getExe' pkgs.dropbear "dropbear"} -F -R -s -D /etc/dropbear'";
    };

    fill-station = {
      # The E-REG bench test exits when done; run it once instead of looping.
      action = if lib.elem "ereg-test" config.fillStation.extraFeatures then "once" else "respawn";
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
