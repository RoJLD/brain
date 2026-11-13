section: Added

- **Where a session ran** (`wi-brain-session-provenance`, `brain.provenance`): session records gain `provider` (the
  model's provider: anthropic, bedrock, vertex, foundry...), `harness` (the tool that ran the session; it takes over
  `tool`, still written and read as its fallback) and `account` with its `plan`. The Stop hook takes the provider from
  the session's environment (`CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`, `CLAUDE_CODE_USE_FOUNDRY`), else the
  model's id; the account is an alias the owner sets in config.json `usage.accounts` (by `since` day, by harness) or
  names with `BRAIN_ACCOUNT`, never an e-mail address nor an account id (such a value is never written, and the SR and
  config.json schemas refuse it). `brain usage` adds a « where » line and `--by provider|harness|account` (`--json`:
  `sources`); `brain status` shows the same breakdown in its tokens row (`tokens.sources`). Old records and ledger
  rows read alike, from their `tool`, model and day.
