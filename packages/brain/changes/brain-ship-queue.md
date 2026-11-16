section: Added

- `brain ship PR`: a local merge queue. A session queues its PR (`<BRAIN_HOME>/ship/queue.json`, once per repo and
  number) and stops; `brain ship --run`, the merger, takes the lock `<BRAIN_HOME>/locks/ship.lock` (one per machine,
  a stale one broken, never on a network share) and ships the queue in order: the merge gate (its `fresh` check
  answered by the catch-up), main merged into the PR with the merge driver, the views regenerated once and `brain
  check`, `brain merge-check`, the targeted tests, then `gh pr merge --match-head-commit`. Every `--batch N` PRs merged
  per repo the full suite runs once, and a bisection names the culprit when it fails. `--list [--json]` shows the
  queue, `--run --dry-run` the plan. A new machine store, `ship` (sealed, truth-local); starting the merger as a
  service is left to the owner.
