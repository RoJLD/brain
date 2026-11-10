section: Added

- `brain usage` shows the subagents and the workflow agents apart (`wi-brain-usage-workflow-agents`). Their
  transcripts (`<session>/subagents/agent-<id>.jsonl`, `<session>/subagents/workflows/<run>/agent-<id>.jsonl`) were
  already read with the session that launched them and counted in its cost. Each ledger row now also says whose that
  cost is (`agents`): the plain subagents by label (the `description` of their `.meta.json`), and each workflow run by
  its id, with its agents, days, phases and labels (the meta's, else the run's `journal.jsonl`; a label written once
  the agent's transcript stopped growing is read at the next scan). `brain usage` prints
  the split between main threads, subagents and workflows; `--by workflow` lists each run with the session that
  launched it, `--by agent` each agent's label, and the summary adds the workflow runs when there are any. A message
  that a subagent's transcript holds is counted once, as the subagent's, even when the parent's transcript copies it.
  `brain usage quota` adds the cost of a session-hour over the last 7 days, the agents' cost included (`session-h`,
  kept in `quota.json`), as information. The usage guard's parallel-sessions cap uses it only when you opt in with
  config.json `usage.guard.session_hour_measured: true` (default false), and then when it is above
  `usage.guard.session_hour_usd`: on a machine whose sessions run workflows, that cap is lower and a new session can be
  refused where it used to pass. By default the cap keeps the configured `session_hour_usd`, so nothing that passed is
  newly refused. `brain usage guard` shows the measured value and whether it is applied (its `session-h` line), and a
  `sessions` refusal names the session-hour it used. The ledger's scanner is now `SCAN_V` 3, so the next
  `brain usage` scans every transcript still on the machine again.
