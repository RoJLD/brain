section: Added

- The floor's ACL step (`wi-brain-floor-acl-lock`, `brain.flooracl`): on a floor-only machine with config.json
  `floor.acl: true` (off by default; Windows), `brain floor lock --apply` also denies the account the sessions run as
  (`--account <SID>`, a user's, which the plan, printed in a normal terminal of that account, puts in the elevated
  command line) every write, delete, ACL or owner change of `~/.claude/settings.json` and `settings.local.json`, of
  `~/.claude/hooks`, `skills`, `commands`, `agents` and `plugins` and all they hold, of the `.claude` folders, settings
  and customization of the brain's projects, and every removal of those through `~/.claude`. What is missing is made
  first, the owner of each path becomes Administrators, no command follows a link (a link among the paths refuses the
  step), the apply checks each deny entry and records the paths in the lock file; on each call the guard then refuses
  every call while one is missing, writable or not the administrators', while the session's account is not the
  locked one or `CLAUDE_CONFIG_DIR` is set. `brain floor status` says whether each is held; `brain floor unlock
  --apply` gives them back first (`--account` when the lock file cannot be read). While locked, Claude Code's own
  writes there fail (docs/guards.md, « The ACL step »).
