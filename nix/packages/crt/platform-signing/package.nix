{ python3, nix, runCommand, writeShellApplication, writeText, symlinkJoin }:
let
  settings = writeText "ground-cache-signing.json" (builtins.toJSON {
    directory = "/var/lib/ground-station/cache-signing";
    name = "crt-ground-station-1";
    nix = "${nix}/bin/nix";
    nixStore = "${nix}/bin/nix-store";
  });
  modules = runCommand "platform-signing-python" { } ''
    mkdir -p "$out/tools/platform"
    touch "$out/tools/__init__.py" "$out/tools/platform/__init__.py"
    cp ${../../../../tools/platform/runtime.py} "$out/tools/platform/runtime.py"
    cp ${../../../../tools/platform/signing.py} "$out/tools/platform/signing.py"
    cp ${../../../../tools/platform/cache_reads.py} "$out/tools/platform/cache_reads.py"
  '';
  provisioner = writeShellApplication {
  name = "crt-provision-cache-key";
  text = ''
    exec ${python3}/bin/python3 -I -c 'import sys; sys.path.insert(0, "${modules}"); from tools.platform.signing import main; sys.exit(main("${settings}"))' "$@"
  '';
  };
  readSettings = writeText "ground-cache-read-check.json" (builtins.toJSON {
    nix = "${nix}/bin/nix";
    nixStore = "${nix}/bin/nix-store";
    fixtureFile = "/etc/ground-cache-read-fixture";
    publicKeyFile = "/var/lib/ground-station/cache-signing/cache.pub";
    origin = "http://127.0.0.1:8080/cache";
  });
  checker = writeShellApplication {
    name = "crt-check-cache-reads";
    text = ''
      exec ${python3}/bin/python3 -I -c 'import sys; sys.path.insert(0, "${modules}"); from tools.platform.cache_reads import main; sys.exit(main("${readSettings}"))' "$@"
    '';
  };
in symlinkJoin {
  name = "ground-cache-administration";
  paths = [ provisioner checker ];
}
