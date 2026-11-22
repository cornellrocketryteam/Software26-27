{ python3, nix, runCommand, writeShellApplication, writeText, settingsFile ? null }:
let
  settings = if settingsFile != null then settingsFile else
    writeText "disabled-daemon-validation.json" (builtins.toJSON {
      enabled = false; fieldMode = true;
    });
  modules = runCommand "platform-validation-python" { } ''
    mkdir -p "$out/tools/platform"
    touch "$out/tools/__init__.py" "$out/tools/platform/__init__.py"
    cp ${../../../../tools/platform/runtime.py} "$out/tools/platform/runtime.py"
    cp ${../../../../tools/platform/validation.py} "$out/tools/platform/validation.py"
  '';
in
writeShellApplication {
  name = "crt-validate-build-daemon";
  runtimeInputs = [ nix ];
  text = ''
    exec ${python3}/bin/python3 -I -c 'import sys; sys.path.insert(0, "${modules}"); from tools.platform.validation import main; sys.exit(main("${settings}"))' "$@"
  '';
}
