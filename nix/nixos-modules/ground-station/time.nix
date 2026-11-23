{ config, lib, ... }:
let
  cfg = config.groundStation.timeServer;
in {
  options.groundStation.timeServer = {
    enable = lib.mkEnableOption "offline-capable LAN time reference";
    upstreamServers = lib.mkOption {
      type = lib.types.listOf (lib.types.strMatching "[A-Za-z0-9.:_-]+");
      default = [];
      description = "Optional upstream NTP hosts; empty keeps the station independent of WAN time.";
    };
  };
  config = lib.mkIf cfg.enable {
    assertions = [{
      assertion = config.groundStation.network.lanInterfaces != [];
      message = "LAN time service requires inspected LAN interfaces.";
    }];
    services.timesyncd.enable = false;
    services.chrony = {
      enable = true;
      servers = cfg.upstreamServers;
      initstepslew.enabled = false;
      makestep.enable = false;
      extraConfig = ''
        # Local reference means LAN agreement, not independently verified UTC.
        local stratum 10
        allow 192.168.1.106/32
        cmdport 0
      '';
    };
    networking.firewall.interfaces = lib.genAttrs config.groundStation.network.lanInterfaces (_: {
      allowedUDPPorts = [ 123 ];
    });
  };
}
