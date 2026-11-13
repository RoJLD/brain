section: Added

- **Where a session ran** (`wi-brain-session-provenance`, `brain.provenance`): `brain usage` adds a « where » line and
  `--by provider|harness|account` (`--json`: `sources`), and `brain status` the same breakdown in its tokens row
  (`tokens.sources`), computed when the report is built: the model's provider (anthropic, bedrock, vertex,
  foundry...: the account's, else the model's id), the harness (the session record's `tool`) and the account with its
  plan, an alias the owner sets in config.json `usage.accounts` (by `since`, a UTC day, and by harness), never an
  e-mail address nor an account id (config.json's schema refuses one; a ledger row holding one shows as `(masked)`).
  Old ledger rows read alike, from their model and day. `usage.accounts` is an optional key, which an older engine
  reads with a note and refuses in strict mode (CI, `BRAIN_STRICT=1`): set it once every machine and the brain's CI run
  this engine. The session record is unchanged: its provenance fields come with `wi-brain-sr-provenance-fields`.
