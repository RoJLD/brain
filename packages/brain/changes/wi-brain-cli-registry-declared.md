section: Changes

- Each command module declares its own phase (`PHASE = "early"` or `"both"`; none for a run-only command), its
  aliases (`ALIASES`) and its `NO_PROJECT`, and `brain.commands._registry.undeclared()` lists a module whose
  declarations disagree with its handlers or its parsers; `tests/test_cli_registry.py` reads them instead of its
  shared EARLY and BOTH lists, so two PRs that each add a command no longer conflict there
  (`wi-brain-cli-registry-declared`).
