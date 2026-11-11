{ config, lib, ... }:
{
  imports = [ ./network.nix ./operator.nix ./storage.nix ./builder.nix ./cache.nix ./cache-ingestion.nix ./ui.nix ./commanding.nix ./telemetry.nix ];

  options.groundStation = {
    virtualMachine = lib.mkOption {
      type = lib.types.bool;
      default = false;
      internal = true;
      description = "Virtual test profile, never physical hardware approval.";
    };
    hardwareConfigured = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Inspected hardware, root mounts and bootloader have been supplied and reviewed for installation.";
    };
    fieldMode = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Inhibit new local builds and ARM worker advertisement during operations. Does not terminate builds already running.";
    };
  };

  config = {
    time.timeZone = lib.mkDefault "UTC";
    time.hardwareClockInLocalTime = false;
    # Clock synchronization may help online but is never a boot prerequisite.
    systemd.services.systemd-time-wait-sync.enable = false;
    powerManagement.enable = false;
    systemd.sleep.settings.Sleep = lib.mkIf config.groundStation.fieldMode {
      AllowSuspend = "no";
      AllowHibernation = "no";
      AllowHybridSleep = "no";
      AllowSuspendThenHibernate = "no";
    };
    services.logind.settings.Login = lib.mkIf config.groundStation.fieldMode {
      IdleAction = "ignore";
      HandleLidSwitch = "ignore";
      HandleLidSwitchExternalPower = "ignore";
    };
  };
}
