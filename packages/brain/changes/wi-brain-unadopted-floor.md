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
- While the floor is on (`brain.floorguard`, docs/guards.md): git configuration from the command line or the
  environment, aliases that cannot be read, a write of git's configuration and any git command but reads in the
  checkout that holds config.json are refused; so are what stops the guards for later sessions (`BRAIN_PYTHON`,
  `CLAUDE_CONFIG_DIR`, `disableAllHooks`, the core plugin turned off, `HOME`, `USERPROFILE` or `PATH` set, the venv
  removed), whatever spells the name or the path; a guard error refuses the call, and `guard.sh` refuses every call
  it cannot judge rather than run PATH's Python. Each check reads what a wrapper or a nested shell runs; git's
  global options are an allowlist; every assignment form of git's, the shell's, the Brain's and Claude Code's
  variables, a copy or an extraction onto what the floor keeps, a write of the registry's Environment key and the
  plugin that runs the guard are refused; an edit is judged on the file it leaves. `hooks.json` runs `guard.sh`
  under `bash -p`.
- The owner guard reads the override's name as the shell and JSON read it (quotes, carets, escapes) and resolves
  a path before comparing it (an NTFS stream's name, a junction); under `guards.owner_strict` it also refuses
  `BRAIN_PYTHON`, `PYTEST_CURRENT_TEST`, `CLAUDE_CONFIG_DIR` and `disableAllHooks` set for later sessions.
  `guard.sh` runs no `BRAIN_PYTHON` whose file name holds no python.
