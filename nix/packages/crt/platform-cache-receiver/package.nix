{ python3, nix, runCommand, writeShellApplication }:
let
  # Keep this closure narrow: no build CLI, credentials, configuration files or
  # repository snapshot. The receiver and its dependencies use only stdlib.
  sources = runCommand "platform-cache-receiver-python" { } ''
    mkdir -p "$out/tools/platform"
    touch "$out/tools/__init__.py" "$out/tools/platform/__init__.py"
    cp ${../../../../tools/platform/runtime.py} "$out/tools/platform/runtime.py"
    cp ${../../../../tools/platform/receipts.py} "$out/tools/platform/receipts.py"
    cp ${../../../../tools/platform/receiver.py} "$out/tools/platform/receiver.py"
  '';
in
writeShellApplication {
  name = "crt-platform-cache-receive-v1";
  runtimeInputs = [ nix ];
  text = ''
    # Isolated Python ignores caller PYTHONPATH, user packages and cwd. Nix
    # operations use the system daemon, never an account-local store/builder.
    export NIX_REMOTE=unix:///nix/var/nix/daemon-socket/socket
    export NIX_USER_CONF_FILES=/dev/null
    exec ${python3}/bin/python -I -c 'import sys; sys.path.insert(0, "${sources}"); from tools.platform.receiver import main; sys.exit(main())' "$@"
  '';
}
