section: Added

- **External calls retry, then step aside** (`wi-brain-net-resilience`). One helper, `brain.net`, now carries the
  engine's calls to GitNexus (its API and MCP endpoint), docker in `brain index`, the ntfy and Telegram channels,
  `git ls-remote` (the update check, `brain tidy --remote`) and `gh pr list` (`brain tidy`): a refused or reset
  connection, or an HTTP 429/502/503/504, is tried again twice with exponential backoff and full jitter; a timeout is
  not. A call that still fails opens the service's circuit breaker for 5 minutes (`<BRAIN_HOME>/net/breakers.json`,
  store `net`, sealed, truth-local): its next calls are skipped at once and said in one line, so a service that is
  down costs one timeout per window. `BRAIN_NET_BREAKER=off` tries every call for a run. A call that succeeds behaves
  as before.
