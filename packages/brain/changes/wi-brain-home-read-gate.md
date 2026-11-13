section: Added

- A read gate on `$BRAIN_HOME` (`wi-brain-home-read-gate`): `brain.classes.home_store(store, exit)` resolves a store
  and an exit to its path or refuses (`classes.Refused`: a secret store whatever the exit, a store `decide` says never
  or sealed for), `classes.home_files(exit)` is the only walk of `$BRAIN_HOME` (it never enters a secret store nor
  follows a link) and `classes.home_names()` lists its top names. The machine probe's size of `$BRAIN_HOME` and the
  uninstaller go through it, and `tests/test_classes_home.py` fails on any other walk of `$BRAIN_HOME` in the engine's
  code (docs/vault.md, « The read gate »). The probe's `brain_home.bytes` no longer counts the secret stores.
