{ lib, python3, nix, git, openssh, bash, coreutils, gawk, runCommand, writeShellApplication }:
let
  source = lib.fileset.toSource {
    root = ../../../..;
    fileset = lib.fileset.unions [
      (lib.fileset.fileFilter (file: file.hasExt "py") ../../../../tools/platform)
      ../../../../tools/flash-ospi.sh
    ];
  };
  modules = runCommand "platform-cli-python" { } ''
    mkdir -p "$out/tools/platform"
    touch "$out/tools/__init__.py" "$out/tools/platform/__init__.py"
    cp ${source}/tools/platform/*.py "$out/tools/platform/"
    cp ${source}/tools/flash-ospi.sh "$out/tools/flash-ospi.sh"
  '';
in
writeShellApplication {
  name = "crt-platform";
  runtimeInputs = [ nix git openssh bash coreutils gawk ];
  text = ''
    exec ${python3}/bin/python3 -I -c 'import sys; sys.argv[0] = "crt-platform"; sys.path.insert(0, "${modules}"); from tools.platform.entry import main; sys.exit(main())' "$@"
  '';
}
