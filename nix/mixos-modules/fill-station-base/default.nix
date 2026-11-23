{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  inherit (config.fillStation) debug ethernetInterface;

  # The one fill-station build used by both init and /bin
  fill-station = pkgs.crt.fill-station.override {
    withHelpers = debug; # ADC CLI tools only in debug
    inherit (config.fillStation) mode operatingProfile;
  };
in
{
  imports = [
    ./fit
    ./options.nix
    ./ospi-image
    ./sd-image
    ./pru-pwm
  ];

  # Keep the tested ARM64 builder default; explicit variants can cross-build
  # from the x86 ground station without changing the board's target platform.
  nixpkgs.pkgs = import inputs.nixpkgs {
    localSystem = config.fillStation.buildSystem;
    crossSystem = {
      config = "aarch64-unknown-linux-musl";
      gcc.cpu = "cortex-a53";
    };
    config.allowUnfreePredicate = package: lib.getName package == "ti-pru-cgt";
    overlays = [
      inputs.self.overlays.default
      inputs.mixos.overlays.default
    ];
  };

  boot.kernelPackages = pkgs.linuxPackagesFor pkgs.crt.fill-station-linux;

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
      action = "respawn";
      process = lib.getExe fill-station;
    };

    time-sync = {
      action = "respawn";
      # Client only: explicit peer bypasses ntp.conf; foreground retains supervision.
      # Missing cable/peer is handled by ntpd retries, independently of application boot.
      process = "${lib.getExe' pkgs.busybox "ntpd"} -n -p ${config.fillStation.timeServer}";
    };

    dhcp = {
      action = "respawn";
      # Retry interface discovery without blocking init or rapidly respawning.
      # Foreground udhcpc keeps renewing leases and retries without a cable.
      process = "sh -c 'until ip link set ${ethernetInterface} up; do sleep 2; done; exec ${lib.getExe' pkgs.busybox "udhcpc"} -f -i ${ethernetInterface}'";
    };
  };

  packages = [
    fill-station
  ]
  ++ lib.optionals debug [
    pkgs.libgpiod
    pkgs.tcpdump
  ];

  etc."dropbear/authorized_keys" = {
    source = ./authorized_keys;
    mode = "0600";
  };

  users.root = {
    uid = 0;
    gid = 0;
    shell = "/bin/sh";
    home = "/root";
  };
  groups.root.id = 0;
}
