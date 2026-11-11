section: Added

- Negative controls for the stranger test's harness: `stranger_test.py --fault rewrite|truncated-ledger|unreached|wrong-engine`
  injects one fault into the upgrade test, and `pytest -m harness` (CI's `harness-controls` job, on a pull request that
  touches the harness) requires each a no-go at the step that guards against it, and the run without a fault a go; a
  test refuses an engine workflow step that writes a command substitution to `GITHUB_OUTPUT` without testing that it is
  not empty (`wi-brain-harness-negative-controls`; docs/formats.md, « Negative controls »).
