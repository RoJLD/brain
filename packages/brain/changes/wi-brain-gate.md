section: Added

- `brain gate`: the pre-push checks of a branch in one call, on the checkout here (or `--repo-dir`): clean (nothing
  left out of HEAD, untracked files included), merge-check (a fresh base merged in, nothing of it lost), review
  (HEAD's review stamp, no finding open, or carried by git's own merge of the base), views (a graph store's views
  regenerated and the store checked: `brain refresh --offline`; a view it rewrote is a change to commit), audit
  (`brain audit --diff`: 0 NEW, 0 LEFT), public (a public repo's HEAD stamped by `brain check --public --history`, a
  valid stamp kept) and tests (`brain test --changed`, `--strict` for the whole suite when the selection widens).
  Every step runs (`--fail-fast` stops at the first failure, `--skip STEP` skips one, said in the verdict); each
  step's command and output go to a log file under `<temp>/brain-gate/<run>/` (or `--logs`, the newest 20 runs
  kept), the report to `verdict.json`, and three lines say what passed, what failed and why, and the next command.
  Exit 0 only when every step that applies passes, 1 otherwise, 2 when it cannot start; `--json` for the report
  (brain.gate, brain.verdict).
