section: Fixes

- `brain audit --json` is byte-stable across runs: the inventory's closure walks each file's edges in sorted order, so
  a unit's `chain` (how the closure reached it) no longer changes with Python's hash seed; a chain may read differently
  once, the first path in sorted order. `brain audit`'s per-repo checks are one function each (`REPO_CHECKS`), the
  findings unchanged; the selftime test of `brain perf --engine` no longer straddles two ISO weeks in the first minutes
  of a Monday UTC (`wi-brain-engine-debt`, batch 3).
