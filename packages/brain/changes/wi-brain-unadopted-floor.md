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
- `brain floor lock` holds the floor by the operating system (`brain.floorlock`, `brain.floorhook`): its plan prints
  the floor it locks and one command line to run from Win+R with Ctrl+Shift+Enter (no shell: an absolute
  interpreter, `-I`, `--wait`; `brain floor unlock` prints its own); `--apply` (elevated only; `--lower` to lower a
  locked floor) installs a new copy of the guard as a system component under `<Program Files>/Brain/guard` (an
  interpreter compiled in place, its code, the plugin's hook scripts, a manifest of hashes with the bytecode), never
  removing the copy its own interpreter runs from, writes Claude Code's managed settings
  (`managed-settings.d/brain-floor.json`: `allowManagedHooksOnly`, so no user, project or plugin hook rewrites a call
  after the guard; the plugin's hooks declared from the copy in exec form, the guard and the governor with
  `onFailure: block`, Claude Code v2.1.295 or later, and a deadline that refuses), checks every file, puts the managed
  file and the lock file back together when a step fails, then writes the lock file (`<ProgramData>/Brain/floor-lock.json`, `/etc/brain`), whose copy of
  the floor is the authority (config.json is only compared to it). Nothing in the user's profile is locked: the
  personal brain's worktrees keep working. Under a lock the guard ignores `BRAIN_GUARD_ALLOW`'s floor names and the
  environment's `BRAIN_HOME`, `BRAIN_PYTHON`, `CLAUDE_PLUGIN_ROOT`; `brain floor unlock --apply` removes all three;
  `brain floor status` walks every file. Under `floor.only`, or wherever a lock exists, the guard refuses every call
  while the lock does not hold (`brain.floor.unlocked`: the session token's effective access, the manifest's hash,
  config.json's floor). While the floor is on, a path piped into a cmdlet that writes and a .NET method that writes
  (`.MoveTo(`, `.CopyTo(`, `.Replace(`, `.Delete(`) are read, and a settings file changes by Write or Edit only (git, an archive or a link that
  would write one is refused), the interpreter's base installation and Python's startup files are kept, git options
  and configuration keys that write or run are refused (an ordinary repo's keys pass), functions of any body, aliases
  and every assignment form are read, and the shell's reserved words are read through (`time -p`, `coproc`). An
  edit that adds a settings file's PreToolUse or PermissionRequest hook, or an env key that picks a shell or git
  (`CLAUDE_CODE_GIT_BASH_PATH`, `CLAUDE_CODE_SHELL*`, `SHELL`, `GIT_EXEC_PATH`, `ComSpec`, `PATHEXT`...), is refused;
  a static member called through a .NET type held in a variable (`$t = [type]'IO.File'; $t::...`) and `Set-Content`
  on the `function:` and `alias:` drives are refused; a network path is judged as written, never resolved; the guard
  runs git by the path the lock names, never from the working directory. While the floor is on, a settings write adds
  only the `env` names of `brain.floor.ENV_ALLOWED` (each with its reason; `BASH_FUNC_*`, `GIT_*` and the rest are
  refused), a write that adds `hooks:` to a skill's, command's or agent's frontmatter is refused, a .NET member reached
  through anything but a literal `[Type]` is refused, and `\\?\` and `\\.\` paths but a drive letter's are judged as
  written. The managed settings also set `strictPluginOnlyCustomization: ["hooks"]`; the guard's copy carries the
  rendered rules and hook contract, and on Windows its hooks run the copy's own engine.
- Under a lock, the guard's refusal names the elevated `brain floor lock --lower` and `brain floor unlock` instead of
  `BRAIN_GUARD_ALLOW`, and `guard.sh` no longer steps aside for the managed file (it judges where the managed
  settings are not in force: Claude Code's managed sources are first-wins).
- The owner guard reads the override's name as the shell and JSON read it (quotes, carets, escapes) and resolves
  a path before comparing it (an NTFS stream's name, a junction); under `guards.owner_strict` it also refuses
  `BRAIN_PYTHON`, `PYTEST_CURRENT_TEST`, `CLAUDE_CONFIG_DIR` and `disableAllHooks` set for later sessions.
  `guard.sh` runs no `BRAIN_PYTHON` whose file name holds no python.
