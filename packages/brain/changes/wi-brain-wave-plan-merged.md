section: Changes

- `brain wave plan` and `brain next` count an item whose PR merged but is not closed yet as done, with
  `brain wave close-merged`'s mapping over the project's repos (git only): out of the lots, the rounds and the quick-win
  slot, a satisfied prerequisite, listed apart in the plan's head (« Merged, to close (N) ») with the
  `close-merged --write` that closes them; a repo that cannot be read is said and leaves its items open, as does a
  repo with no changelog fragment folder (a planning repo's titles name the items they file). A merged item that still
  holds work (a standing debt item, `props.left`, `props.external_blocker`) stays open, listed « merged, work left,
  kept open » (another wave's, « kept open outside the wave »); while one is kept, the advice is to close the others by
  hand, as `close-merged --write` would close the kept ones too.
  `brain wave plan --include-merged` keeps them in the lots, said merged; `--no-merged` reads no PR (the plan as before).
- `brain wave close-merged` reads the merged PRs in one `git log` instead of one `git diff` a PR (a range of hundreds of
  PRs took tens of seconds); same mapping.
