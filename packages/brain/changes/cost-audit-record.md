section: Added

- `brain cost audit --write` also appends its record, one JSON line (`v: 1`), to
  `<BRAIN_HOME>/usage/<project>/audits.jsonl`: the window, its sessions and cost, the estimates' error (backtests,
  the share within x1.5, the typical factor, the window's items and how many were off) and the context counts. The
  audit gains a section « Context against the budgets »: the sessions whose brief gave a context budget, how many
  passed 80 % and 100 % of it, and the sessions that peaked above 400k with their cost. The weekly task's command
  is unchanged; the records are the week-by-week series a KPI reads (the last line of a window wins).
- `brain digest`'s token cost section names the latest cost audit: its window, the estimates' typical error, the
  sessions past their budget, and its file.
