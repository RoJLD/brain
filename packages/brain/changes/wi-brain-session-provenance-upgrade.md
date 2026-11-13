section: Upgrade

**Name your accounts, once every machine and the brain's CI run this engine** (optional): config.json
`usage.accounts`, a list of `{"alias", "plan", "since", "harness", "provider"}` (only `alias` required; an alias is a
short name, never an e-mail address). The session record gains four optional fields (`provider`, `harness`, `account`,
`plan`) and config.json the `usage.accounts` key, which an older engine reads with a note and refuses in strict mode
(CI, `BRAIN_STRICT=1`). Without `usage.accounts`, `brain usage` and `brain status` show the account as `(none)`.
