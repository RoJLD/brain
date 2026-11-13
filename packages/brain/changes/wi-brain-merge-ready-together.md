section: Added

- `brain merge-ready PR --with PR... [--test] [--python P]` (`wi-brain-merge-ready-together`, `brain.mergetogether`):
  PRs green alone checked as they will be merged, together. Each passes the gate alone; then the heads are merged on
  the base in the order given by `git merge-tree` with the repo's merge driver (nothing checked out), a head that
  conflicts with one before it left out with its files; the same merges made as plain text say which PR GitHub will
  see conflicting once those before it merge (merge the base into it locally, push). The tests `brain impact` chooses
  for the set are listed, and `--test` runs them in a scratch worktree of the integrated commit. Ready: each head's
  stamp names the PRs it was checked with and the merge order (`together`).
