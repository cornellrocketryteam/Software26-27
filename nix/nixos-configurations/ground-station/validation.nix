# One-shot administrative validation profile; never enables normal/remote builds.
{ ... }:
{
  groundStation.fieldMode = false;
  groundStation.builder.validation.enable = true;
}
