section: Changes

- `guard.sh` without a Python that imports brain, the floor off, refuses `set_remote_control` and
  `set_session_permission_mode` and asks the card for `archive_session` (it let them through to the card before): the
  owner's allow rules never pass them unguarded. The guard's tool matcher gets a 30 s timeout (10 before), its git
  calls 3 s each: a hook Claude Code kills lets the call through. A machine with a locked floor runs
  `brain floor lock --apply` again for the new matcher: until then its allow rules for those tools are withheld.
- The allow rules a guard bounds wait for it (`brain.permissions.GUARD_REQUIRED`, fail closed): an allow rule that lets
  `set_remote_control` or `archive_session` through is withheld where the PreToolUse hooks Claude Code runs do not send
  that tool to the guard (a floor lock's managed settings, else the core plugin installed at user scope, enabled, hooks
  not all off; unreadable is unseen). `brain permissions render` leaves it out and lists it as expired
  (`install.ps1 -Apply` takes it out of the settings, its line `withheld`, the user render's JSON key `withheld`);
  `brain permissions check` fails on it, `brain check` and `brain doctor` warn of it. Such a rule is refused outside the user levels
  (engine, global, profile, machine): a project's settings are shared by every machine.
- The guards read the desktop app's session files at each call, never the index's cache
  (`brain.sessions.app_index(cached=False)`, `app_cache`), and refuse a session's write into those files, their
  folders (any account folder under `Claude-Data`, a new one too), that cache, a session's transcript or a folder
  that would bring one into the transcripts' folder, also through a hard link (`brain.guards.app_files`, category
  `override`, edit tools and shell writes). Under `guards.owner_strict` a session no longer disables the core plugin
  (`enabledPlugins` false in Claude Code's settings, `claude plugin disable` or `uninstall` of it).
- The archive case's git calls run with none of the hook's `GIT_` variables, no system or global config (but their
  line endings) and hooks off, 15 s for all of them, and only once the target repo's config declares no filter driver
  nor include and the checkout has no submodule nor nested repo (else the card): no program of the target repo runs
  in the hook.
