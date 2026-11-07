{
  pkgsCross,
  buildOptee,
  buildPackages,
  fetchFromGitHub,
}:
let
  pkgsCross32 = pkgsCross.armv7l-hf-multiplatform;
  version = "4.8.0";
in
buildOptee {
  inherit version;
  platform = "k3-am64x";

  src = fetchFromGitHub {
    owner = "OP-TEE";
    repo = "optee_os";
    rev = version;
    hash = "sha256-eefwfjSkDMFubKk+tIzTqe7h+v3VYxV6gzpzFxuJsyU=";
  };

  # Preserve ARM32 TAs alongside the builder's default ARM64 target.
  depsBuildBuild = [
    buildPackages.stdenv.cc
    pkgsCross32.stdenv.cc
  ];

  extraMakeFlags = [
    "CROSS_COMPILE32=${pkgsCross32.stdenv.cc.targetPrefix}"
    "CFG_USER_TA_TARGETS=ta_arm32 ta_arm64"
  ];
}
