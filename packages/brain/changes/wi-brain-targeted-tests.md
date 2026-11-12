section: Added

- Targeted tests (`wi-brain-targeted-tests`): `brain test --changed [BASE]` selects the test modules a change touches
  by the store's coverage map (`coverage/<repo>.json`, or `--map FILE`) and runs them first: the tests that ran a
  changed module's functions or import it, a changed module level's importers transitively, a changed test or
  `conftest.py`'s folder. Fail-safe: no map, a dirty or foreign one, a file coverage cannot see (docs, data) or a
  module the map never measured widens the answer to the whole suite, and static evidence only adds a test. It starts
  in shadow mode: the selection runs, a widened answer is left to the CI's whole suite, and each run is a line of
  `<BRAIN_HOME>/ledger/targeted-tests.jsonl`; `--strict` runs the whole suite when the answer widens, `--list` and
  `--json` print the selection, `--inert GLOB` declares paths no test reads. See docs/tests-graph.md.
