section: Added

- `brain alerts`, `brain status` (without `--quick`) and the cockpit's probe raise a dirty main checkout: a registered
  repo's main checkout with modified or untracked files (`git --no-optional-locks status --porcelain`, 10 s at most;
  ignored files and `.claude/worktrees/` left out) is `checkout:<repo>` at warn, naming the first files and the last
  session whose working folder it was; one git cannot read is the same key at info, or keeps its last known alert
  when it was dirty; one checkout spanned by several projects alerts once, in the project whose root it is; a
  project's `alerts: levels: {checkout: ...}` sets the dirty level (`wi-brain-main-checkout-clean`).
