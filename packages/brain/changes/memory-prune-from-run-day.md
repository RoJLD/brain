section: Fixes

- `brain memory sync` counts its two weeks of kept branches from the run's day, not the wall clock, so a run dated in the past keeps its own branches, and a `day` that is no ISO date is refused before anything is pushed.
