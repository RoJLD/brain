section: Added

- Generated READMEs (`wi-brain-readme-sync`): a repo opts in by holding `readme.yaml` at its root (a new format,
  `schemas/readme.schema.json`: what the repo is, why, how to start, its notes, the commands its README quotes).
  `brain docs render [--write [--force]] [--repo R] [--dir PATH]` writes its `README.md` from the engine's template
  and the facts of their sources (the features recap with a link to the repo's `FEATURES.md`, written too; each
  quoted command's usage from its `--help`; a private repo's active specs, recent ADRs and pending milestones), a
  public repo's render neutral. `brain docs check` exits 1 when `readme.yaml` misses a field, a quoted command is
  gone, or `README.md` is not the render; `brain check` runs it (a stale README is a stale view), `brain audit`
  measures `readme.yaml` and `help.quoted` in an opted-in repo, and close-item renders and checks it. A repo without
  `readme.yaml` is never read: nothing is newly refused.
