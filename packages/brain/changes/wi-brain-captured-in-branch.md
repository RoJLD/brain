section: Changes

- `brain decision answer --captured` records each answer where its DDR lives: one whose DDR only the asking
  session's branch holds (asked there, not merged yet) is written, refreshed, committed and pushed on that branch,
  carried by that branch's PR, instead of a fresh worktree from main where that DDR does not exist; one whose DDR the
  default branch holds keeps the PR from the default branch, judged on its copy (answered meanwhile, stale, a
  default); a mixed batch takes both in one run, with one result. A checkout with uncommitted changes is refused; a
  failure before the branch's commit puts the checkout back as it was; a failed push exits non-zero with git's
  message; `--dry-run` says where each answer would go (`wi-brain-captured-in-branch`).
