section: Fixes

- `brain tidy --apply` deletes a merged local branch by compare-and-delete once origin's default branch (or the local one) holds its tip, instead of `git branch -d`, which refused every branch merged since the clone's own main last moved; a branch that moved after the plan is kept (`wi-brain-tidy-branch-delete`).
