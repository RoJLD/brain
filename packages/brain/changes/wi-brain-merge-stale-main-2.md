section: Added

- The push guard `merges:stale`: a `git push` of a branch whose merge of the base is not on the remote yet fetches
  the base again (once, bounded) and runs `brain merge-check` against the base as merged and the fresh one. It
  refuses a merge that lost a line or a node, and a watched file the merge resolved against a main that has moved on
  it since (`wi-brain-merge-stale-main-2`; override `BRAIN_GUARD_ALLOW=merges:stale`). `brain merge-check` reads only
  the files main changed since the merge base.
