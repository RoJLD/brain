section: Added

- `brain usage` shows the subagents and the workflow agents apart (`wi-brain-usage-workflow-agents`). Their
  transcripts (`<session>/subagents/agent-<id>.jsonl`, `<session>/subagents/workflows/<run>/agent-<id>.jsonl`) were
  already read with the session that launched them and counted in its cost. Each ledger row now also says whose that
  cost is (`agents`): the plain subagents by label (the `description` of their `.meta.json`), and each workflow run by
  its id, with its agents, days, phases and labels (the meta's, else the run's `journal.jsonl`). `brain usage` prints
  the split between main threads, subagents and workflows; `--by workflow` lists each run with the session that
  launched it, `--by agent` each agent's label, and the summary adds the workflow runs when there are any. A message
  that a subagent's transcript holds is counted once, as the subagent's, even when the parent's transcript copies it.
  `brain usage quota` adds the cost of a session-hour over the last 7 days, the agents' cost included (`session-h`,
  kept in `quota.json`). The ledger's scanner is now `SCAN_V` 3, so the next `brain usage` scans every transcript
  still on the machine again.
