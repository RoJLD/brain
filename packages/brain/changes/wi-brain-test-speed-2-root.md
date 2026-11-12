section: Added

- **`BRAIN_TEST_ROOT`** (`wi-brain-test-speed-2`): one folder for the brain suite's temporary files, pytest's
  temporary folders under `<root>/tmp` (`PYTEST_DEBUG_TEMPROOT`, so pytest keeps its numbering and its last three
  runs; an explicit `--basetemp` wins) and the harness tests' venvs under `<root>/venvs`; unset, the system's temp
  folder as before. A short folder keeps pip's paths in those venvs under Windows' length limit and is one place an
  owner can exclude from an on-access antivirus scan (about 10 % of the suite's time measured with the temporary
  folders excluded); the engine never changes the antivirus (`packages/brain/README.md`, « Tests »).
