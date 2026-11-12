section: Added

- A signal no longer cuts a write: every command runs under `brain.shutdown.graceful()`, so SIGINT, SIGTERM, SIGHUP
  and Ctrl+Break stop it once the ledger line or the atomic state write in progress is whole, with its `finally`
  blocks run and its locks released; stderr names the signal and the command ends by it (POSIX) or exits 128 + its
  number (Windows). The interactive
  cockpit (`brain tui`) and the scheduled alerts pass (`brain alerts --notify`) run once per machine
  (`<BRAIN_HOME>/locks/`): a second cockpit is refused, a second pass skipped (`wi-brain-graceful-shutdown`).
