section: Added

- The review error score (`wi-brain-review-error-score`): `brain review stamp` takes `--pr`, `--item` (its wave
  places the stamp), `--wave` and `--stream`, and keeps the note's finding lines (`- high correctness A.b fixed:
  ...`: severity, lens, root-cause family, outcome, found before or after the merge, covered by a script) as the
  stamp's rows; `brain review score [--wave W] [--json]` counts each PR once by its latest stamp, the confirmed
  findings per PR by severity, lens and root cause, the trend per wave, and the owner's rule: the reviews lighten
  only once the findings per PR fall over two waves in a row. `brain retro --wave` and the cockpit's health tab show
  it (docs/review.md, « The error score »).
