section: Changes

- `brain review stamp HEAD --note FILE` without `--findings`/`--fixed` takes its counts from the note's finding
  lines: findings (a refuted line recorded as `refuted`, never open), fixed, contested; a note with no finding line is
  refused. A stamp is refused while the worktree holds a change HEAD lacks, and with `--pr` (a GitHub remote) unless
  the head is the PR's pushed head. `brain review rounds` counts the same note stamped on the PR's next head as a
  re-stamp of its round, not a new round (`wi-brain-review-stamp-from-note`).
- A script or session that stamped with `--pr` before its push now pushes first: stamp HEAD without `--pr` for
  `brain gate`, push, then stamp it again with `--pr` (docs/review.md, « 3. The stamp »); keep the note outside the
  checkout, where an untracked file counts as a change HEAD lacks.
