{ lib, stdenvNoCC, fetchurl, qemu, proot, path, makeWrapper }:
let
  i386Libc = (import path { system = "i686-linux"; }).glibc;
  x86Libc = (import path { system = "x86_64-linux"; }).glibc;
  emulator = "${qemu}/bin/qemu-i386";
in stdenvNoCC.mkDerivation {
  pname = "ti-pru-cgt";
  version = "2.3.3";
  src = fetchurl {
    url = "https://dr-download.ti.com/software-development/ide-configuration-compiler-or-debugger/MD-FaNNGkDH7s/2.3.3/ti_cgt_pru_2.3.3_linux_installer_x86.bin";
    sha256 = "1f1405167214f2c0ef848591b17a7799fdcd9f55f11bc90db9ace3490d426215";
  };
  dontUnpack = true;
  nativeBuildInputs = [ makeWrapper proot ];
  installPhase = ''
    runHook preInstall
    cp $src installer
    chmod +x installer
    export PROOT_NO_SECCOMP=1
    proot -q "${emulator} -L ${i386Libc} -E GLIBC_TUNABLES=glibc.rtld.execstack=2" \
      -b ${i386Libc}/lib:/lib \
      ./installer --mode unattended --prefix "$TMPDIR/ti"
    mkdir -p $out
    cp -r "$TMPDIR/ti/ti-cgt-pru_2.3.3/"* $out/
    mkdir $out/libexec
    for program in $out/bin/*; do
      if [ -f "$program" ] && [ -x "$program" ]; then
        name=$(basename "$program")
        mv "$program" "$out/libexec/$name"
        makeWrapper ${proot}/bin/proot "$out/bin/$name" \
          --add-flags "-q '${qemu}/bin/qemu-x86_64 -L ${x86Libc}' -b ${x86Libc}/lib:/lib64 $out/libexec/$name" \
          --set PROOT_NO_SECCOMP 1 \
          --set C_DIR "$out/include;$out/lib" \
          --set PRU_C_DIR "$out/include;$out/lib" \
          --prefix PATH : "$out/bin"
      fi
    done
    $out/bin/clpru --compiler_revision
    runHook postInstall
  '';
  # These are host tools emitting PRU ELF files, never board runtime binaries.
  meta = {
    description = "Pinned TI PRU compiler running through QEMU on Linux builders";
    license = lib.licenses.unfreeRedistributable;
    platforms = lib.platforms.linux;
  };
}
