{
  config,
  lib,
  pkgs,
  ...
}:
let
  # Debug builds add tools that are too big for the production (OSPI) image.
  debug = false;

  # The one fill-station build used by both init and /bin, compiled with the
  # feature selected by fillStation.mode (see ./mode.nix)
  fill-station = pkgs.crt.fill-station.override {
    withHelpers = debug; # ADC CLI tools only in debug
    inherit (config.fillStation) mode;
  };
in
{
  imports = [
    ./fit
    ./mode.nix
    ./ospi-image
    ./sd-image
  ];

  nixpkgs.buildPlatform = "aarch64-linux"; # TODO: Replace and sense current build platform
  nixpkgs.hostPlatform.config = "aarch64-unknown-linux-musl";

  boot.kernel = pkgs.crt.fill-station-linux;

  etc."hosts".source = pkgs.writeText "etc-hosts" ''
    127.0.0.1      localhost
    ::1            localhost
  '';

  init = {
    shell = {
      tty = "ttyS2";
      action = "askfirst";
      process = "/bin/sh";
    };
    sshd = {
      action = "respawn";
      # -R writes the host key under /etc/dropbear, which must be a real
      # directory in the writable /etc overlay (an etc."dropbear" entry would
      # be a symlink into the read-only store). The key is regenerated each boot.
      # -D reads ./authorized_keys from there too; root's home (/) is read-only.
      # -s: key login only (password login never worked here; serial is the fallback).
      process = "sh -c 'mkdir -p /etc/dropbear && ln -sf ${./authorized_keys} /etc/dropbear/authorized_keys && exec ${lib.getExe' pkgs.crt.dropbear-minimal "dropbear"} -F -R -s -D /etc/dropbear'";
    };

    fill-station = {
      action = "respawn";
      process = lib.getExe fill-station;
    };

    wpa_supplicant = {
      action = "respawn";
      process = "${lib.getExe' pkgs.wpa_supplicant "wpa_supplicant"} -i wlan0 -c /etc/wpa_supplicant.conf";
    };

    mount_data = {
      action = "wait";
      # busybox mount has no -L; resolve the label with busybox findfs instead
      process = "sh -c 'mkdir -p /tmp/data && (mount -t vfat \"$(findfs LABEL=DATA)\" /tmp/data || mount -t vfat /dev/mmcblk1p2 /tmp/data || mount -t vfat /dev/mmcblk0p2 /tmp/data)'";
    };

    dhcp = {
      action = "respawn";
      process = "${lib.getExe' pkgs.busybox "udhcpc"} -f -i wlan0";
    };
  };

  bin = [
    pkgs.crt.dropbear-minimal
    pkgs.libgpiod
    fill-station
    pkgs.iw
    pkgs.wpa_supplicant
  ]
  ++ lib.optionals debug [
    pkgs.tcpdump
    pkgs.util-linux
  ];

  etc."lib/firmware".source = pkgs.runCommand "wl18xx-firmware" { } ''
    mkdir -p $out/ti-connectivity
    cp ${pkgs.crt.ti-linux-firmware}/ti-connectivity/wl18xx-fw-4.bin $out/ti-connectivity/wl18xx-fw-4.bin
  '';

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
    home = "/";
  };
  groups.root.id = 0;

  etc."shadow".source = pkgs.writeText "fill-station-shadow" ''
    ${config.users.root.name}:$6$cy4JUqDYWZowMaLn$oefiZuEJvrHqU3zB33WKrLxaBrsh8mdYqLvtZHP8X1b48E3MYGAYJ3vXtL9x83AI8H6TVO9rvBcsq7bu11li20:1::::::
  '';
}
