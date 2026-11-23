section: Added

- `brain standards score [--json]`: a project's scorecard on its standards. Each applicable row scores from the new
  `projects.yaml` `standards.coverage` key (`{id: status}` or `{id: {status, by}}`, the statuses of a row's own
  coverage): 2 for have, 1 for partial, 0 for none or not said (listed, so the score is a floor), a row of n/a left
  out; the points by catalog and domain, the total, its percent and its band (prototype, production from 18 of 34,
  hardened from 28 of 34). `brain standards check` and `brain check --all` check the key (a mapping, known statuses,
  known ids). The software catalog gains five rows from a grid of resilience pillars (95 rows): `sw-debt-tracked`,
  `sw-hot-paths`, `sw-sobriety`, `sw-alert-runbooks` and `sw-onboarding-time` (`wi-brain-standards-score`).
