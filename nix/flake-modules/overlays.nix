{
  # Overrides only for packages something else pulls in implicitly; variants we
  # reference ourselves belong in nix/packages (e.g. crt.wpa-supplicant-minimal)
  flake.overlays.default =
    final: prev:
    {
      # flashcp (defaults to off in busybox's Kconfig) writes FITs to the OSPI
      # flash from Linux; see tools/flash-ospi.sh.
      busybox = prev.busybox.override {
        extraConfig = ''
          CONFIG_FLASHCP y
        '';
      };

      libgpiod = prev.libgpiod.overrideAttrs (oldAttrs: {
        configureFlags =
          (oldAttrs.configureFlags or [ ])
          ++ final.lib.optionals final.stdenv.hostPlatform.isMusl [
            # AC_FUNC_MALLOC is broken on cross builds.
            "ac_cv_func_malloc_0_nonnull=yes"
            "ac_cv_func_realloc_0_nonnull=yes"
          ];
      });
    }
    # pkgs.crt.<name> from nix/packages/crt/<name>/package.nix (not exported as flake `packages`)
    // prev.lib.packagesFromDirectoryRecursive {
      inherit (final) callPackage;
      inherit (prev) newScope;
      directory = ../packages;
    };
}
