{ linuxKernel, linux_6_18 }:
let
  configfile = ./kernel.config;

  # Fail if any option in required.config is not =y in the resolved config.
  # `make oldconfig` in the build resolves the config silently, so without this
  # a dependency change could quietly drop a driver the board needs.
  checkRequired = ''
    missing=0
    while IFS= read -r line; do
      case "$line" in "" | "#"*) continue ;; esac
      if ! grep -qxF "$line" "$buildRoot/.config"; then
        echo "required kernel option not set: $line" >&2
        missing=1
      fi
    done < ${./required.config}
    if [ "$missing" -ne 0 ]; then
      echo "kernel config is missing options from required.config" >&2
      exit 1
    fi
  '';

  kernel = linuxKernel.manualConfig {
    inherit (linux_6_18) src version modDirVersion;
    inherit configfile;
  };
in
kernel.overrideAttrs (old: {
  postConfigure = (old.postConfigure or "") + checkRequired + ''
    # kernel.config should already be fully resolved; warn if the build changed it
    if ! diff -u \
        <(grep -E '^(CONFIG_|# CONFIG_)' ${configfile}) \
        <(grep -E '^(CONFIG_|# CONFIG_)' "$buildRoot/.config") >&2; then
      echo "warning: kernel.config is not fully resolved; regenerate it with resolvedConfig" >&2
    fi
  '';

  passthru = old.passthru // {
    # Configure-only build: merge am64x.fragment into kernel.config, resolve it
    # with olddefconfig using the same toolchain as the real build, and output
    # the result. See am64x.fragment for the workflow.
    resolvedConfig = kernel.overrideAttrs {
      pname = "fill-station-linux-config";

      configurePhase = ''
        runHook preConfigure
        mkdir build
        export buildRoot="$(pwd)/build"

        scripts/kconfig/merge_config.sh -m -O "$buildRoot" ${configfile} ${./am64x.fragment}
        make "''${makeFlags[@]}" olddefconfig

        ${checkRequired}

        # Every fragment line must survive olddefconfig. A disabled option may
        # also vanish entirely when its dependencies are gone, which is fine.
        unapplied=0
        while IFS= read -r line; do
          case "$line" in
            "# CONFIG_"*" is not set")
              sym="''${line#\# }"; sym="''${sym%% is not set}"
              if grep -q "^$sym=" "$buildRoot/.config"; then
                echo "fragment not applied (still enabled): $line" >&2; unapplied=1
              fi ;;
            CONFIG_*)
              if ! grep -qxF "$line" "$buildRoot/.config"; then
                echo "fragment not applied: $line (got: $(grep "^''${line%%=*}=" "$buildRoot/.config" || echo unset))" >&2
                unapplied=1
              fi ;;
          esac
        done < ${./am64x.fragment}
        if [ "$unapplied" -ne 0 ]; then
          echo "some am64x.fragment lines were overridden by olddefconfig (see above)" >&2
          exit 1
        fi
        runHook postConfigure
      '';

      dontBuild = true;
      dontFixup = true;

      installPhase = ''
        mkdir -p $out
        cp "$buildRoot/.config" $out/config
        scripts/diffconfig ${configfile} "$buildRoot/.config" > $out/diffconfig.txt || true
        echo "$(wc -l < $out/diffconfig.txt) option(s) changed; see $out/diffconfig.txt"
      '';
    };
  };
})
