# Live media is separate from the installed station: console access here never
# enables password SSH or root login in the embedded UM560 system.
{ lib, pkgs, modulesPath, groundStationSystem, ... }:
let
  helper = pkgs.writeShellApplication {
    name = "crt-install-um560";
    runtimeInputs = [ pkgs.coreutils pkgs.util-linux pkgs.nix pkgs.nixos-install-tools ];
    text = builtins.replaceStrings [ "@system@" ] [ (toString groundStationSystem) ]
      (builtins.readFile ../../../tools/platform/install-um560.sh);
  };
in
{
  imports = [ (modulesPath + "/installer/cd-dvd/installation-cd-minimal.nix") ];
  networking.hostName = "ground-station-installer";
  image.baseName = lib.mkForce "crt-ground-station-um560-installer";
  isoImage.volumeID = "CRT_GS_INSTALL";
  isoImage.storeContents = [ groundStationSystem ];
  # Install a prebuilt closure; a channel or internet fetch is unnecessary.
  system.installer.channel.enable = false;
  services.openssh.enable = lib.mkForce false;
  services.getty.helpLine = lib.mkForce ''
    CRT UM560 OFFLINE FOUNDATION INSTALLER
    Local live-console login: nixos (sudo without password).
    Nothing installs automatically. Read /etc/crt-um560-install.txt.
    Run crt-install-um560 for help. SSH is disabled on this live image.
  '';
  environment.systemPackages = [ helper ];
  environment.etc."crt-um560-install.txt".text = ''
    This is a fresh-install FOUNDATION, not the operational telemetry release.
    The owner accepts loss of old Ubuntu/container data. No backups are required.
    No disk is selected, partitioned or formatted automatically.

    Boot this USB in UEFI mode. Inspect lsblk and identify the intended internal
    SSD by model, capacity and device path; do not select the installer USB.
    Prepare a GPT disk with a 1 GiB EFI System partition and remaining ext4 root.
    Format EFI as FAT32 with label CRT-GS-EFI and root ext4 as CRT-GS-ROOT.
    Mount root at /mnt and EFI at /mnt/boot. The labels must be unique.
    Exact manual commands and precautions are in the repository install runbook.

    sudo crt-install-um560 --check
    sudo crt-install-um560 --install

    Installation uses the embedded closure, without network downloads or builds.
    Set the prompted ground-admin console password, then reboot/remove the USB.
    SSH on the installed system is key-only as ground-admin, not root.
    Ethernet MAC 58:47:CA:7E:6E:15 becomes lan0 using DHCP. Reserve the desired IP
    at the router. UI is on port 8080; /readyz remains 503 until field acceptance.
    Telemetry, cache, builder and commands are not enabled in this foundation.
    If password setup is interrupted, finish it from this live system with:
      sudo nixos-enter --root /mnt --command 'passwd ground-admin'
    This media remains a local recovery environment after installation.
  '';
  # Keep serial output available for disposable, NIC-free media boot checks.
  boot.kernelParams = [ "console=tty0" "console=ttyS0,115200" ];
}
