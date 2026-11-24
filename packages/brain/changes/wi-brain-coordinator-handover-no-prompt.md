section: Added

- The guard's archive case (`brain.guards.archive`, `wi-brain-coordinator-handover-no-prompt`): the desktop app's
  `mcp__ccd_session_mgmt__archive_session` now goes through `guard.sh tool` (hooks.json's matcher). It passes, logged
  `allowed` with its case, only for a finished session the caller started (`child`, not a coordinator) or for the
  caller's predecessor at a hand-over (`predecessor`: a coordinator by name or a chain root whose live, detached
  coordinator successor the caller is, its hand-over note written), with none of the target's children blocking,
  every PR of its app file merged or closed and each of its folders (`cwd`, `worktreePath`) gone or the top of a
  checkout with no change and nothing ignored but caches (the archive removes its worktree). Any other call, an
  unlogged pass and an error get `permissionDecision: ask`: the owner's card, which no allow rule lifts. So an owner's
  allow rule for `archive_session` lifts the card only inside those conditions (`docs/guards.md`, « The archive
  case »). `brain.sessions.app_work` reads a session's PR states and folders from its own app file.
- `brain.permissions.GUARD_BOUNDED`: the exact allow rule `mcp__ccd_session_mgmt__set_remote_control` no longer falls
  in `security-settings` (`check`, `grant`, `render`, `explain`); `brain.guards.remote_control` refuses every call
  outside its three cases. Any other rule naming Remote Control stays never grantable.
