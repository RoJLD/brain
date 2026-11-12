section: Added

- **The background waiter's hint** (`wi-brain-stuck-waiters`, `waithint.sh`, `brain.waithint`): a Bash or PowerShell
  call run in the background whose `until` or `while` loop has no deadline, no process check and no check that its
  file is still there gets one line of hook context (bound it, exit when the file or process is gone, stop the
  background tasks before the cleanup), never a refusal; `BRAIN_WAIT_HINT=0` turns it off. The brief's after-merge
  lines and close-item's step 5 add: no background task left at the cleanup or the archive (the app refuses to
  archive a session with live work).
