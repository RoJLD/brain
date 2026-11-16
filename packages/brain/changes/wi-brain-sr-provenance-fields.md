section: Added

- **Session records say where a session ran** (`wi-brain-sr-provenance-fields`, `brain.provenance`): an SR gains
  `provider` (anthropic, bedrock, vertex, foundry...), `harness` (the tool that ran the session; it takes over `tool`,
  still written and read as its fallback) and `account` with its `plan`, written by the Stop hook, `brain record sr`
  and `brain record backfill`. The Stop hook takes the provider from the session's environment
  (`CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`, `CLAUDE_CODE_USE_FOUNDRY`), else the account's, else the
  model's id; the account is the config.json `usage.accounts` entry in force, or the alias `BRAIN_ACCOUNT` names in
  the session's environment (two accounts on one machine, a switch within a day), never an e-mail address nor an
  account id (the hook leaves such a value out and says so in `errors.log` without it; the SR schema refuses it). A
  rebuilt record keeps the values it had. `brain usage` and `brain status` read them first, and still compute them
  for a record without them. The SR schema moves (four optional fields under `v` 1): the release is a minor.
