section: Added

- `brain vault canary --due` seals only when the canary is due: a recipient never sealed, failing or sealed more than
  20 hours ago, or this machine's key not opening its own since; otherwise `canary not due`, exit 0. A schedule
  `{command: vault canary --due, at: '07:30', at_logon: true}` catches up, at the first logon after a boot, a daily run
  the machine was off for, when the Task Scheduler's `StartWhenAvailable` does not, and never seals twice a day
  (`wi-brain-canary-boot-catchup`, docs/vault.md).
