section: Changes

- The three append-only files that grew with no retention are logs of their own now (`stateio.LOG_RETENTION`):
  `usage/starts.jsonl` (the governor's brainstorm starts, 2 months) and `usage/quota.jsonl` (the quota readings, 12
  months) rotate monthly into `<stem>-YYYY-MM.jsonl` like `errors.log`, and the notifications' audit
  (`notify/YYYY-MM.jsonl`) drops the months past 6. `quota.load_readings` reads every monthly file, the governor the
  live file and the newest month, so the month's turn hides nothing (`stateio.log_files`). An older engine after a
  rollback reads only the live file: less history, nothing refused (`wi-brain-logs-unclassified`).
