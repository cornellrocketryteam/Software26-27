{ config, lib, ... }:
let
  cfg = config.groundStation.network;
  hasLan = cfg.lanInterfaces != [ ];
in
{
  options.groundStation.network = {
    lanInterfaces = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Inspected trusted LAN interface names. Empty keeps SSH and HTTP on loopback. Configure DHCP reservations/DNS on the existing router.";
    };
    webPort = lib.mkOption {
      type = lib.types.port;
      default = 8080;
      description = "Foundation HTTP port, opened only on the configured LAN interfaces.";
    };
  };

  config = {
    networking.useDHCP = lib.mkDefault true;
    networking.firewall = {
      enable = true;
      interfaces = lib.genAttrs cfg.lanInterfaces (_: {
        allowedTCPPorts = [ 22 cfg.webPort ];
      });
    };
    systemd.network.wait-online.enable = false;
    services.openssh = {
      enable = true;
      openFirewall = false;
      listenAddresses = [ { addr = if hasLan then "0.0.0.0" else "127.0.0.1"; port = 22; } ];
      settings = {
        PasswordAuthentication = false;
        KbdInteractiveAuthentication = false;
        PermitRootLogin = "no";
        X11Forwarding = false;
      };
    };
    # No fabricated peer pins. Populate programs.ssh.knownHosts with reviewed
    # public host keys before any system service connects to a peer.
    programs.ssh.extraConfig = ''
      Host *
        StrictHostKeyChecking yes
    '';
  };
}
