section: Added

- The machine's IPC token kept from sessions (`wi-brain-ipc-token-read-guard`): under config.json
  `guards.refuse_token_read: true` (off by default), the owner guard's new check `token` (`brain.tokenguard`) refuses
  a session's `Read`, `Grep`, tool edit or shell call that reaches `<BRAIN_HOME>/ipc/token` (or
  `$BRAIN_IPC_TOKEN_FILE`): any program but the ones that read only a name or metadata, through wrappers and nested
  shells, an input redirection, a glob, a link, inline code that names it; a new PreToolUse hook `guard.sh read` on
  Read and Grep, which starts Python only when the call names `ipc`, `token` or the brain's home, or reads a link.
  The MCP server refuses it whatever the key, and redacts the token from every answer (docs/guards.md, « The
  machine's token »).
