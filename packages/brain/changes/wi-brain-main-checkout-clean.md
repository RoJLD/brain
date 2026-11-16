section: Added

- `brain alerts` and `brain status` (without `--quick`) raise a dirty main checkout: a registered repo's main checkout
  with modified or untracked files (`git status --porcelain`, 10 s at most) is `checkout:<repo>:dirty` at warn,
  naming the first files and the last session whose working folder it was; one git cannot read is
  `checkout:<repo>:unread` at info; a project's `alerts: levels: {checkout: ...}` sets the level
  (`wi-brain-main-checkout-clean`).
