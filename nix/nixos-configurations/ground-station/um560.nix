# Fresh-install foundation for the inspected UM560. Labels describe the NEW
# filesystems; importing/building this module never formats the existing disk.
{ ... }:
{
  groundStation = {
    hardwareConfigured = true;
    network.lanInterfaces = [ "lan0" ];
    operatorUi.enable = true;
  };

  boot.initrd.availableKernelModules = [ "nvme" "xhci_pci" "usb_storage" "usbhid" "sd_mod" ];
  boot.loader = {
    systemd-boot = { enable = true; configurationLimit = 5; };
    efi = { canTouchEfiVariables = true; efiSysMountPoint = "/boot"; };
  };
  fileSystems = {
    "/" = { device = "/dev/disk/by-label/CRT-GS-ROOT"; fsType = "ext4"; };
    "/boot" = {
      device = "/dev/disk/by-label/CRT-GS-EFI";
      fsType = "vfat";
      options = [ "umask=0077" ];
    };
  };
  hardware = {
    cpu.amd.updateMicrocode = true;
    enableRedistributableFirmware = true;
  };

  networking = {
    useNetworkd = true;
    useDHCP = false;
    networkmanager.enable = false;
    wireless.enable = false;
  };
  # Ubuntu calls this NIC eno1. A MAC match gives the new installation a stable
  # name independent of the installer/kernel's predictable-name selection.
  systemd.network = {
    links."10-ground-lan" = {
      matchConfig.MACAddress = "58:47:ca:7e:6e:15";
      linkConfig.Name = "lan0";
    };
    networks."20-ground-lan" = {
      matchConfig.Name = "lan0";
      networkConfig.DHCP = "ipv4";
      linkConfig.RequiredForOnline = "no";
    };
  };
}
