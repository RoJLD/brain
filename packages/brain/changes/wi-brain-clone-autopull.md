section: Added

- The owner's engine clone kept current: `brain refresh` fast-forwards it (`git fetch`, then `git merge --ff-only`)
  when it is on its remote's default branch, no tracked file has a change, no merge, rebase, cherry-pick or revert
  is in progress and the remote brings no file it ignores here; otherwise it says why in one line and leaves it as it
  is: never a switch, a commit, a reset or a stash. Each git call is bounded (60 s, its process tree stopped). The
  clone is `config.json` `engine.clone` (optional, new: absolute, `~` or relative to the config's folder; set it once
  every machine and CI run this release), else the registry's checkout whose remote is `engine.repo`; `--offline` or
  `--no-clone` skip it (`brain.engineclone`; `wi-brain-clone-autopull`).
