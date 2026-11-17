section: Added

- `brain ship PR`: a local merge queue. A session queues its PR (`<BRAIN_HOME>/ship/queue.json`, once per repo and
  number; a PR of another repo than the checkout's refused) and stops; `brain ship --run`, the merger, takes the lock
  `<BRAIN_HOME>/locks/ship.lock` (one per machine, kept while its process runs, a dead holder's broken, never on an
  untrusted file system) and ships the queue in order: the merge gate (its `fresh` check answered by the catch-up; a
  fork PR or a branch that is the base refused), main merged into the PR with the merge driver, the views
  regenerated once and `brain check`, `brain merge-check`, the targeted tests with `--strict`; a caught-up head is
  stamped by the public check before its push, its CI awaited and the merge gate run on it again with nothing
  waived; then `gh pr merge --match-head-commit` and the PR read back. Every `--batch N` PRs merged per repo and base
  the full suite runs once, a confirmed bisection names the culprit when it fails, and the red base's PRs wait until
  `--run --force`. `--list [--json]` shows the queue, `--run --dry-run` the plan. A new machine store, `ship`
  (sealed, truth-local); starting the merger as a service is left to the owner.
- `brain merge-ready`: a head that only merges the base into a reviewed head (git's own merge, nothing resolved by
  hand) carries that head's review stamp.
- An atomic state write (`brain.stateio`) retries for a second when Windows refuses to replace a file another
  process holds open.
