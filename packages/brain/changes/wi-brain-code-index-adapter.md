section: Added

- The code index as an adapter (`brain.codebackends`, `docs/code-index.md`): `brain index`, `brain code-map`,
  `brain impact` and `brain health code-index` pick a backend, GitNexus (the default, the code authority for search)
  or codebase-memory-mcp (`brain.cbm`: its binary under `$BRAIN_HOME/code-index/cbm`, run as a stdio MCP server for
  the time of a command), each declared in the tier registry (`code-index-gitnexus`, `code-index-cbm`) with its
  fallback. `brain impact` on a worktree asks codebase-memory-mcp first (`detect_changes` on the checkout in place,
  no push needed) and each is the other's fallback; `brain index --backend cbm` indexes the declared repos in place
  and is the default when no stack declares `index:`; `--backend gitnexus|cbm` names one. The engine sets CBM's
  `ui_enabled`, `auto_watch`, `watcher_enabled` and `auto_index` to false before every session and `brain health
  code-index` says `UNSAFE` when one is on (`wi-brain-code-index-adapter`).
