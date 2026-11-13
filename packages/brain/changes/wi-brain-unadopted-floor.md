section: Added

- The locked floor (`wi-brain-unadopted-floor`, `brain.floor`): a line of the owner's rules marked `<!-- lock -->`
  (or `<!-- lock: ID -->`) is locked, and the guard's new `floor` refusals hold the floor: a session's `git push` to
  `main` or `master` (check `main`) and a forced push (check `force`), under the new optional config.json key
  `floor.refuse: true` (default false). `floor.only: true` makes a machine floor-only until it is adopted: only the
  locked rules are injected, only the floor's refusals, the secrets and the configuration checks run, and the memory
  notes are not synced either way. `BRAIN_GUARD_ALLOW=floor` lifts the refusals, the owner's.
