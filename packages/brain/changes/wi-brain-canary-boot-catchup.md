section: Added

- `brain vault canary --due HH:MM` seals only when the day's canary of a daily run at HH:MM is not done: a recipient
  with no canary sealed to its current key since the latest HH:MM (local time), a failing one, one within 2 hours of
  `canary_hours`, or this machine's key not having opened its own since; it says why, else prints `canary not due`
  and exits 0. A schedule `{command: vault canary --due 07:30, at: '07:30', at_logon: true}` seals at 07:30 each day,
  catches up at the first logon after a boot a run the machine was off for, when the Task Scheduler's
  `StartWhenAvailable` does not, and never seals twice a day (`wi-brain-canary-boot-catchup`, docs/vault.md).
