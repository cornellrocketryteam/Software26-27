# nanopb source tree (runtime C files + generator), used by fill-station's
# build.rs via NANOPB_DIR. Fetched here instead of vendored into the repo.
{ fetchFromGitHub }:
fetchFromGitHub {
  owner = "nanopb";
  repo = "nanopb";
  rev = "nanopb-0.4.9.2";
  hash = "sha256-kkwFhsGssr+Hl6yHCUuCQXNl1i2EZ5jFdF10+ekHK1w=";
}
