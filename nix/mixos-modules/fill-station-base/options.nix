{ lib, ... }:
{
  options.fillStation = {
    ethernetInterface = lib.mkOption {
      type = lib.types.strMatching "eth[0-9]+";
      default = "eth0";
      description = "Wired Linux interface used for DHCP; verify the CPSW port in the board serial console.";
    };
    buildSystem = lib.mkOption {
      type = lib.types.enum [ "aarch64-linux" "x86_64-linux" ];
      default = "aarch64-linux";
      description = "Linux machine executing the build tools; the board target remains ARM64 musl.";
    };
    # Selects both the Cargo feature compiled into fill-station and the matching
    # pinmux profile (see ./fit), so the binary and pin wiring can't disagree.
    mode = lib.mkOption {
      type = lib.types.enum [
        "none"
        "liquid"
        "hybrid"
      ];
      description = "Fill-station build mode (Cargo feature passed to the fill-station package).";
    };

    debug = lib.mkEnableOption "debug tools (ADC CLI helpers, tcpdump, util-linux), too big for the production (OSPI) image";
  };
}
