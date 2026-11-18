section: Changed

- `brain tidy` is applied where work ends, not only reported. `brain close ID --pr "repo #N" --write` removes the PR's
  head branch and its worktrees at once: the PR's merge stands for tidy's 24-hour idle rule, so a worktree made with
  `git worktree add` that no desktop-app session knows no longer waits a day (never an unmerged branch, a dirty,
  locked or leased worktree). The head branch counts as merged when its tip is on the head commit the PR merged (gh's
  `headRefOid`), so a squash or rebase merge is tidied too; a tip with commits the PR did not merge is kept. The one
  the shell stands in is kept, and the output names the `cd` out of it; a worktree kept says why, after `--write`
  too. `brain item close --pr` prints that `brain close` line.
- `brain refresh` first applies the merged-and-clean part of `brain tidy`'s plan of its projects' repos while the new
  `config.json` key `tidy.auto` is on (the default): the stale worktrees on a merged branch or detached on a commit the
  default branch holds, the merged local branches, the worktrees whose folder is gone; never origin's branches, an
  unmerged branch, a dirty, locked or leased worktree, nor the current folder. A failure is a warning line, never a
  failed refresh. `--no-tidy` skips it once; `tidy.auto: false` turns it off. The refreshes that `brain gate`,
  `brain ship` and the answers' worktree run pass `--no-tidy`: a check never deletes.
- Neither `brain close` nor `brain refresh` removes a worktree holding files git ignores, which `git worktree remove`
  deletes without asking (a hand-placed `.env`, local data, outputs; caches and virtual environments such as
  `__pycache__` or `.venv` aside): it is kept and the paths are named. `brain tidy --apply` keeps it too (the
  coordinator's scripted step after an archive) and says so; the new `--include-ignored` removes it with those files,
  which its plan names under the worktree. An ignored junction or folder link is not counted: tidy unlinks it first,
  never following it.
- The close-item procedure's step 5 removes the worktree with `brain close`, never by hand, and the coordinator runs
  `brain tidy --apply` on a child's repos right after archiving it; the brief's after-merge lines say so.
