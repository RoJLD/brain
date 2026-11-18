section: Added

- `brain test --changed --verdict`: the verdict mode of the targeted tests, for a session that would otherwise run a
  long suite in the background and poll it. The selection and pytest's whole output go to a log file
  (`<temp>/brain-test/<run>/pytest.log`, the newest 20 runs kept, or `--log FILE`); the run blocks until it ends or
  its deadline (`--deadline S`, 540 seconds by default, under a shell tool's ten minutes), when its process tree is
  stopped and the exit code is 124 (an interrupt stops it too); three lines come out: PASSED, FAILED or TIMEOUT with
  pytest's counts and the log, the failed and erroring tests' ids, the next command (the run's own flags kept).
  `--json` adds them to the selection's JSON ([docs/tests-graph.md](docs/tests-graph.md)).
