section: Added

- A signal no longer cuts a write: every command runs under `brain.shutdown.graceful()`, so SIGINT, SIGTERM, SIGHUP
  and Ctrl+Break stop it once the ledger line or the atomic state write in progress is whole, with its `finally`
  blocks run and its locks released; the exit is 128 + the signal's number and stderr names it. The interactive
  cockpit (`brain tui`) and the scheduled alerts pass (`brain alerts --notify`) run once per machine
  (`<BRAIN_HOME>/locks/`): a second cockpit is refused, a second pass skipped (`wi-brain-graceful-shutdown`).
