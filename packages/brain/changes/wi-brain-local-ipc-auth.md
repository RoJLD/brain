section: Added

- `brain health ipc` (and `--all`; `wi-brain-local-ipc-auth`, `brain.ipchealth`): whether the Brain's local services
  bind loopback and require the machine's token where they can check one, and whether their containers run as a
  user. It checks the token file, the MCP
  server's 401 without the token, and each running container of the Brain's Compose projects and code index (FAIL for
  a port published beyond loopback, a warning as root), and names what takes requests without the token. Under
  `--all` it is silent, probing nothing, on a machine that never made the token and requires none.
- The collector can require the machine's token, opt-in: config.json `ipc.require_token: [otel-collector]` (a new
  optional key, with `ipc.mcp_port`); `brain bundle apply` then renders otelcol-contrib's `bearertokenauth` on every
  OTLP receiver and mounts the token as a secret. Claude Code's export needs
  `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <token>` then (docs/mcp.md, « The Brain's other local services »).
