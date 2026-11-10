section: Added

- `brain review prep [PR | BASE..HEAD]`, `brain review stamp HEAD` and `brain review check HEAD`: the review before
  the report, its zero-token part (`wi-brain-review-step`, `docs/review.md`). The packet holds the diff, the touched
  files at the head, `brain audit --diff`'s output and the lenses the touched surfaces call for (correctness always;
  security, compatibility, install and upgrade, procedure, tests, docs); the session's lens agents and two skeptics
  per distinct finding read it; the stamp, keyed by the head's full sha, records the counts for the error score and
  is what the merge gate checks.
