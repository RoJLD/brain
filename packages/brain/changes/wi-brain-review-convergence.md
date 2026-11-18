section: Added

- `brain review rounds PR`: the review rounds of a PR from its stamps (one per head: findings, high, fixed, contested, open) and the stop rule: not converging when the high findings have not halved over the last 3 rounds (`--rounds N`), the next step a structural decision rather than another round; it says, never refuses. `brain review stamp --high H` records a round's high findings (else the note's high lines are read) (`wi-brain-review-convergence`).
