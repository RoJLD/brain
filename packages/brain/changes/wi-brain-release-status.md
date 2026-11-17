section: Added

- `brain release status [X.Y.Z]`: where a release stands, at zero token: its wave closed, the version PR merged, the
  tag cut and signed, the pin PR merged, the engine installed and verified on this machine, each done, pending or
  unknown, then the next step and whose it is (`--offline`, `--json`); `brain release verify`: the after-install
  checks in one call (the engine against the pin, `brain probes`, `brain classes --check`, the brain's tests), each
  logged under `$BRAIN_HOME/release/`, recorded for `status` (docs/release.md, « Where a release stands »;
  `wi-brain-release-status`).
