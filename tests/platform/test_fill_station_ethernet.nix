{ flake }:
let
  lib = flake.inputs.nixpkgs.lib;
  check = name:
    let c = flake.mixosConfigurations.${name}.config;
    in
    assert lib.assertMsg (c.fillStation.ethernetInterface == "eth0") "wired interface must default to eth0";
    assert lib.assertMsg (!(c.init.wpa_supplicant.enable or false)) "Wi-Fi must not start automatically";
    assert lib.assertMsg (!(c.etc ? "wpa_supplicant.conf")) "wired image must not embed Wi-Fi credentials";
    assert lib.assertMsg (c.init.dhcp.action == "respawn"
      && lib.hasInfix "-f -i eth0" c.init.dhcp.process
      && lib.hasInfix "ip link set eth0 up" c.init.dhcp.process)
      "wired DHCP must raise the interface and remain supervised";
    { interface = c.fillStation.ethernetInterface; inherit (c.init.dhcp) process; };
in
lib.genAttrs [ "fill-station" "fill-station-liquid" "fill-station-debug" ] check
