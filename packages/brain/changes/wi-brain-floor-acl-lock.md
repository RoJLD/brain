section: Added

- The floor's ACL step (`wi-brain-floor-acl-lock`): on a floor-only machine with config.json `floor.acl: true` (off
  by default; Windows), `brain floor lock --apply` also denies the account the sessions run as (`--account <SID>`,
  which the plan, printed in a normal terminal of that account, puts in the elevated command line) every write,
  delete, ACL or owner change of `~/.claude/settings.json` and `settings.local.json`, of `~/.claude/hooks`, `skills`,
  `commands` and `agents` and all they hold, of the settings and `.claude` folders of the brain's projects, and every
  removal through `~/.claude`; what is missing is made first, the owner of each path becomes Administrators, the
  apply checks each deny entry and records the paths in the lock file, whose per-call check then refuses every call
  while one is missing or writable. `brain floor status` says whether each is held; `brain floor unlock --apply` gives
  them back first. While locked, Claude Code's own writes there fail (docs/guards.md, « The ACL step »).
