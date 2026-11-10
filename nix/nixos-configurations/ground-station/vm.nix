{ modulesPath, lib, ... }:
{
  imports = [ (modulesPath + "/virtualisation/qemu-vm.nix") ];
  groundStation.virtualMachine = true;
  networking.hostName = lib.mkForce "ground-station-vm";
  virtualisation = {
    memorySize = 2048;
    cores = 2;
    diskSize = 8192;
    graphics = false;
  };
  # No password/autologin or host port forwarding. This VM is a separate target,
  # not evidence about the UM560's bootloader, disks, NICs or operator display.
}
