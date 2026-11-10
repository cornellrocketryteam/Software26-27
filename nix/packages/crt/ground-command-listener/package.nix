{ python3, writeShellApplication }:
let
  python = python3.withPackages (ps: [ ps.pyserial ps.websockets ]);
in
writeShellApplication {
  name = "ground-command-listener";
  runtimeInputs = [ python ];
  text = ''
    exec ${python}/bin/python ${../../../../ground-station/LaunchButton/pc_listener.py} "$@"
  '';
}
