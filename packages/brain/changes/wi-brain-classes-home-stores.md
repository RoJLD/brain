section: Changes

- Every store the engine writes under `$BRAIN_HOME` has a class (`wi-brain-classes-home-stores`, COMPAT-6):
  `brain.classes.ENGINE_STORES` grows from 6 to 35 (usage, budget, forecast, announce, handover, inbox, features,
  cache, memory-sync, schedules, alerts, notify, secrets (secret), the telemetry collector's data, stacks, telemetry,
  code-index, code-map, public-check, reviews, backup, tui.json, update.json, personal.json, profile.json,
  code-index.json, venv, bin, the engine's tag clones), each with a suggested data class and a format class
  (truth-local, log, derived, install, external). An engine store a brain does not declare is no longer an error of
  `brain check --all` and `brain classes --check`: it takes its suggested class (never looser than sealed), the check
  notes it, and `brain classes PATH` and `classes.decide` use that default. A name at the top of `$BRAIN_HOME` that no
  store covers is noted, sealed by default. `brain classes --suggest`, for a brain that already declares classes,
  prints only the engine stores it misses; `brain init` declares them all. `brain classes` lists the sources the
  engine reads and never writes: the desktop app's session metadata, read through a closed list of keys (never
  `lastTurnReport`, `pendingSystemReminder`, `promptAppendSnapshot`, `remoteMcpServersConfig`, `spawnSeed`), its
  worktrees and its shared notes. A test fails on a name the engine's code writes under `$BRAIN_HOME` that the list
  does not hold, and another on a text key of the app's metadata reaching a store.
