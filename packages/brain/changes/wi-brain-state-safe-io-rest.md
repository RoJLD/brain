section: Changes

- **Nothing to run for the machine-local state** (`wi-brain-state-safe-io-rest`): `tui.json`,
  `memory-sync/state.json`, `vault/device.json`, the session files under `sessions/` and the budget watch's states
  gain `"v": 1` at their next write, which an older engine reads unchanged. Each may now have a `<name>.bak` beside
  it, and one that was unreadable a `<name>.unreadable-<stamp>`: both are safe to delete once looked at.
  `ledger/errors.log` now moves aside each month as `errors-YYYY-MM.log` (kept six months); an `errors.log.1` left by
  the old 1 MB cut can be deleted. `install.ps1 -Apply` stops on a `~/.claude/settings.json` that is not a JSON object
  (« fix it by hand first ») instead of failing in the middle of its writes, and leaves `settings.json.bak` beside it
  at each write.
- **The rest of the machine-local state goes through `brain.stateio`** (`wi-brain-state-safe-io-rest`,
  spec-brain-data-compat N4; `docs/formats.md`, « Machine-local state »): a backup beside the file, an atomic synced
  write, an unreadable file set aside by the next write, a newer brain's file read but never written. It now carries
  the cockpit's `tui.json` (the keys this engine does not know are kept through a save; `brain tui` says when a newer
  brain's file keeps it from remembering the views), `memory-sync/state.json` (a newer record stops the sync before
  any fetch, in `last.json` and the alert), `vault/device.json` (`device init` and `forget-previous` refuse a newer
  file before the keystore is touched; `device init --rotate` keeps the keys a newer brain added with the same `v`),
  the Stop hook's session snapshot and state, the end-of-turn report, the plan file and the budget watch's
  `budget/<session>.json` (a newer one is left to its brain, the mark set ahead so bash starts no Python meanwhile;
  the prune takes the backups too). A symbolic link is written through: the file it points to changes, the link
  stays.
- **A foreign file is edited in its own keys only**: `brain.stateio.read_foreign` / `write_foreign`, and through them
  `permissions.ClaudeCode.write` (`brain permissions render --write`, `--level session --out`), refuse a settings file
  that cannot be read or is not a JSON object (never replaced) and one Claude Code wrote meanwhile (run again), back it
  up beside itself unless git keeps it as it is (`permissions.kept_by_git`: tracked and unchanged; a gitignored
  `settings.local.json` is backed up), then write atomically. `install.ps1` writes `~/.claude/settings.json` with the
  same policy (`Read-ForeignJson`, `Write-ForeignJson`; an empty file is read as a missing one).
- **The log class**: `ledger/errors.log` moves aside each month, or past 1 MB, as `errors-YYYY-MM[-n].log`, kept six
  months (`brain.stateio.rotate_log`, which never moves a log over a rotated one when hooks rotate at once);
  `stateio.LOG_RETENTION` holds each log class's retention (errors 6 months, the engine's timing 3, the ledgers of
  records kept), and `brain.selftime` prunes through it.
