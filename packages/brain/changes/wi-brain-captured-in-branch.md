section: Changes

- `brain decision answer --captured` records the batch on the asking session's branch when that branch holds every
  captured DDR and the default branch lacks one of them (asked there, not merged yet): written, refreshed, committed
  and pushed there, carried by that branch's PR, instead of a fresh worktree from main where those DDRs do not exist;
  a checkout with uncommitted changes is refused (`wi-brain-captured-in-branch`).
