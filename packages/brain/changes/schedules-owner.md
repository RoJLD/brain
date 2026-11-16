section: Added

- A project's `schedules_owner: {file, apply, floors}` in the registry names where the tasks its own installer
  registers change: `brain schedule list` shows each found task's file and apply command, its floor when it is a
  collector, and `BELOW FLOOR` when its cadence is slower, it has none or it is disabled; a floored task missing from
  the scheduler is said under the list; `brain check --all` checks the key (SCHED-1, `wi-brain-schedule-settings`).
