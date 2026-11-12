section: Added

- The push guard `merges:stale`: a `git push` of a branch that carries a merge of the base fetches the base again
  (bounded) and runs `brain merge-check` against the base as merged and the fresh one. It refuses a resolution that
  lost a line or a node, and one made against a main that has moved since on a watched file the branch changes too
  (`wi-brain-merge-stale-main-2`; override `BRAIN_GUARD_ALLOW=merges:stale`).
