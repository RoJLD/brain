section: Upgrade

1. **Nothing to run for the rest of the machine-local state** (`wi-brain-state-safe-io-rest`). `tui.json`,
   `memory-sync/state.json`, `vault/device.json`, the session files under `sessions/` and the budget watch's states
   gain `"v": 1` at their next write, which an older engine reads unchanged. Each may now have a `<name>.bak` beside
   it, and one that was unreadable a `<name>.unreadable-<stamp>`: both are safe to delete once you have looked.
   `ledger/errors.log` now moves aside each month as `errors-YYYY-MM.log` (kept six months); an `errors.log.1` left
   by the old 1 MB cut stays as it is and can be deleted. `install.ps1 -Apply` now stops on a `~/.claude/settings.json`
   that is not a JSON object (« fix it by hand first ») instead of failing in the middle, and leaves
   `settings.json.bak` beside it at each write.
