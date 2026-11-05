{ inputs, ... }:
{
  imports = [
    inputs.treefmt-nix.flakeModule
  ];

  perSystem.treefmt = {
    settings.on-unmatched = "info";
    flakeCheck = false;

    # Third-party, generated, and lock files keep their upstream formatting
    settings.global.excludes = [
      "fill-station/vendor/*"
      "rats/StepperPico/AccelStepper-*/*"
      "*/pnpm-lock.yaml"
    ];

    programs.nixfmt.enable = true;
    programs.rustfmt.enable = true;
    programs.prettier.enable = true;
    programs.ruff-format.enable = true;
    programs.shfmt.enable = true;
  };
}
