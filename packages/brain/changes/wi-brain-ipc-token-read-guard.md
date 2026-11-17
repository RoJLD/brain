section: Added

- The machine's IPC token kept from sessions (`wi-brain-ipc-token-read-guard`): under config.json
  `guards.refuse_token_read: true` (off by default), the owner guard's new check `token` (`brain.tokenguard`) refuses
  a session's `Read`, `Grep`, tool edit or shell call that reaches `<BRAIN_HOME>/ipc/token` (or
  `$BRAIN_IPC_TOKEN_FILE`): any program naming the file, its folder or `<BRAIN_HOME>` itself but the ones that read
  only a name or metadata (and those too in a pipe), through wrappers and nested shells, a redirection, a glob, a
  link, a PowerShell list or join, inline code or a heredoc that names it; Read and Grep through a new opt-in hook,
  `tokenguard.sh`, which `brain render` registers only when the key is on. The MCP server runs the check whatever the
  key, and redacts the token from every answer (docs/guards.md, « The machine's token »).
