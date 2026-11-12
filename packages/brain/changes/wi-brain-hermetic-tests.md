section: Changes

- The engine's tests run in a hermetic environment, an allow list (`wi-brain-hermetic-tests`): every `BRAIN_*`,
  `CLAUDE*`, `GIT_*` and `RESEARCH_GRAPH_*` variable, a GitHub token and the editor are cleared unless the conftest
  pins them or a test sets them, and git reads an empty global configuration and no system one; the suite gives the
  same result from a desktop-app session, a terminal or CI. `tests/test_hermetic.py` lists the variables the engine
  reads and fails on one left set without a reason, and on any `monkeypatch.undo()` in the tests.
