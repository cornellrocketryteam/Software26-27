{
  perSystem =
    { pkgs, ... }:
    {
      apps.hardware-config.program = pkgs.writeShellScriptBin "hardware-config" ''
        exec ${pkgs.python3}/bin/python3 ${../../fill-station/hardware}/server.py "$@"
      '';
    };
}
