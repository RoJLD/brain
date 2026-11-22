section: Added

- The owner's engine clone kept current: `brain refresh` (and `brain release apply`) fast-forward it with
  `git pull --ff-only` when it is on its remote's default branch, no tracked file has a change and no merge, rebase,
  cherry-pick or revert is in progress; otherwise they say why in one line and leave it as it is: never a switch, a
  commit, a reset or a stash. The clone is `config.json` `engine.clone` (optional, new: absolute, `~` or relative to
  the config's folder), else the registry's checkout whose remote is `engine.repo`; `--offline` or `--no-clone` skip
  it (`brain.engineclone`; `wi-brain-clone-autopull`).
