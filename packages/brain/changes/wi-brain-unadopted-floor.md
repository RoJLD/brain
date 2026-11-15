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
- `brain floor lock` holds the floor by the operating system (`brain.floorlock`): its plan prints what it gives to
  the administrators (config.json's checkout and its .git, the pointer, the guard's venv and code, the plugin folder
  that carries `guard.sh`; owner Administrators or root, the users read and run only, inheritance cut) and the
  commands; `--apply` runs them in an elevated terminal only and writes the machine's lock file last
  (`<ProgramData>/Brain/floor-lock.json`, `/etc/brain/floor-lock.json`); `--refresh` fast-forwards the locked checkout
  to origin/main first; `brain floor unlock` gives them back; `brain floor status` says whether a session can change
  them. The guard reads the floor from config.json and the lock file (`brain.floor.effective`; an unreadable file
  holds it); under `floor.only`, or wherever a lock exists, it refuses every call while a path the lock holds is
  within the session token's reach (`brain.floor.unlocked`: the token's effective access, not the read-only
  attribute). While the floor is on, a settings file changes by Write or Edit only (git, an archive or a link that
  would write one is refused), the interpreter's base installation and Python's startup files are kept, git options
  and configuration keys that write or run are refused (an ordinary repo's keys pass), functions of any body, aliases
  and every assignment form are read, and the shell's reserved words are read through (`time -p`, `coproc`).
- The owner guard reads the override's name as the shell and JSON read it (quotes, carets, escapes) and resolves
  a path before comparing it (an NTFS stream's name, a junction); under `guards.owner_strict` it also refuses
  `BRAIN_PYTHON`, `PYTEST_CURRENT_TEST`, `CLAUDE_CONFIG_DIR` and `disableAllHooks` set for later sessions.
  `guard.sh` runs no `BRAIN_PYTHON` whose file name holds no python.
