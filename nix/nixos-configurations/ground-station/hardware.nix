{ config, lib, ... }:
{
  # Deliberately no disks, mount IDs, bootloader, NIC or USB identities here.
  # Import the inspected machine's hardware-configuration.nix and bootloader
  # configuration before setting hardwareConfigured. This is not install media.
  assertions = [
    {
      assertion = config.groundStation.virtualMachine || (
        config.groundStation.hardwareConfigured
        && config.fileSystems ? "/"
        && config.fileSystems."/".device != null
      );
      message = "ground-station hardware installation prerequisite: import the inspected hardware/filesystem and bootloader configuration, then set groundStation.hardwareConfigured = true. Use ground-station-vm for virtual testing; this scaffold is not bare-metal ready.";
    }
  ];
}
