{ python3, nix, runCommand, writeShellApplication }:
let
  # Only stdlib helper dependencies belong in the worker closure.
  sources = runCommand "platform-worker-python" { } ''
    mkdir -p "$out/tools/platform"
    touch "$out/tools/__init__.py" "$out/tools/platform/__init__.py"
    cp ${../../../../tools/platform/runtime.py} "$out/tools/platform/runtime.py"
    cp ${../../../../tools/platform/worker.py} "$out/tools/platform/worker.py"
  '';
in
writeShellApplication {
  name = "crt-platform-worker-v1";
  runtimeInputs = [ nix ];
  text = ''
    export NIX_REMOTE=unix:///nix/var/nix/daemon-socket/socket
    export NIX_USER_CONF_FILES=/dev/null
    exec ${python3}/bin/python -I -c 'import sys; sys.path.insert(0, "${sources}"); from tools.platform.worker import main; sys.exit(main())' "$@"
  '';
}
