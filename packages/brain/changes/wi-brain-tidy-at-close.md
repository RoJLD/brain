section: Changed

- `brain tidy` is applied where work ends, not only reported. `brain close ID --pr "repo #N" --write` removes the PR's
  head branch and its worktrees at once: the PR's merge stands for tidy's 24-hour idle rule, so a worktree made with
  `git worktree add` that no desktop-app session knows no longer waits a day (never an unmerged branch, a dirty,
  locked or leased worktree). The one the shell stands in is kept, and the output names the `cd` out of it; a worktree
  kept says why, after `--write` too. `brain item close --pr` prints that `brain close` line.
- `brain refresh` first applies the merged-and-clean part of `brain tidy`'s plan of its projects' repos while the new
  `config.json` key `tidy.auto` is on (the default): the stale worktrees on a merged branch or detached on a commit the
  default branch holds, the merged local branches, the worktrees whose folder is gone; never origin's branches, an
  unmerged branch, a dirty, locked or leased worktree, nor the current folder. A failure is a warning line, never a
  failed refresh. `--no-tidy` skips it once; `tidy.auto: false` turns it off. The refreshes that `brain gate`,
  `brain ship` and the answers' worktree run pass `--no-tidy`: a check never deletes.
- The close-item procedure's step 5 removes the worktree with `brain close`, never by hand, and the coordinator runs
  `brain tidy --apply` on a child's repos right after archiving it; the brief's after-merge lines say so.
