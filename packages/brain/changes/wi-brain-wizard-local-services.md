section: Added

- A Local services step in the setup wizards, for any owner: the cockpit's Setup page gains six optional steps in
  their order (the machine's token, Claude Code's OTLP export and its `otelHeadersHelper` shown as the exact settings
  lines, the collector requiring the token by a PR, the sovereign bundle, `brain health ipc`, Cursor's MCP server
  rendered), each a logged brain command, the owner's own steps kept as plans; `brain init` prints them among its next
  steps. `brain ipc token --plan` says what `--init` would do and exits 0 (`wi-brain-wizard-local-services`).
