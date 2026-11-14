section: Added

- The locked floor (`wi-brain-unadopted-floor`, `brain.floor`): a line of the owner's rules marked `<!-- lock -->`
  (or `<!-- lock: ID -->`) is locked, and the guard's new `floor` refusals hold the floor: a session's `git push` to
  `main` or `master` (check `main`, read as git reads it: `@`, `:`, wildcards, `push.default`, `remote.<name>.push`,
  `git -c`), a forced push (check `force`, long-option prefixes included) and a write of the config.json the guard
  reads, of its pointer or of a variable that chooses it (check `config`), under the new optional config.json key
  `floor.refuse: true` (default false). `floor.only: true` makes a machine floor-only until it is adopted: only the
  locked rules are injected, only the floor's refusals, the secrets and the configuration checks and the owner
  guard's override category run (no session lifts its own floor), and the memory notes are not synced either way.
  `BRAIN_GUARD_ALLOW=floor` lifts the refusals, the owner's.
