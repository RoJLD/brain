section: Added

- `brain session-archive run [--dry-run] [--max N]`, opt-in (`session_archive.enabled` in config.json, off by default;
  no scheduled task is created): the agents' transcripts (Claude Code's sessions and their subagents, quiet for 2
  hours, changed since archived) copied line by line with each row a residency filter matches replaced by a stub
  (`session_archive.resident`, `{name: regex}`: the owner's patterns, the engine names no source), scanned by the
  engine's secret patterns then by gitleaks, each line it reports dropped and a second pass required clean, then sealed
  into the spool (`brain.spool.put`, store `session-archive`, class sealed, a new engine store) and indexed by session
  record in `$BRAIN_HOME/session-archive/index.json` (machine of origin, the session's place in the tree, what was
  dropped). gitleaks absent or failing: nothing is archived. `--dry-run` lists what would be archived and dropped and
  seals nothing. `brain session-archive status`; `brain health session-archive` gives the age of the last archive
  (`wi-brain-session-archive`).
