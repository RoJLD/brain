section: Added

- `brain release prepare X.Y.Z --theme T`: the version PR's mechanical part in one command, a plan then `--write` in
  order, stopping at the first step that fails: both `__version__`, the research-graph pin, `brain_version`, the
  install lines and the stranger test's `--ref` (only the lines that name the previous version); `freeze_store.py vP`
  (skipped once frozen); `changelog.py compile`; `FEATURES.md` and `docs/reference/` rendered from the planning brain
  (with `--force`: the release's engine is ahead of that brain's pin until its pin PR, which its `views.strict` would
  refuse); `release_check.py --store`, then its `--preview`. It names what stays a model's: the Upgrade steps' prose, the pilot
  page's line and the review (`wi-brain-release-prepare`).
