section: Added

- `brain ipc otel-headers` prints the OTLP export's headers, `{"Authorization": "Bearer <token>"}`, for Claude Code's
  `otelHeadersHelper` setting: the export authenticates to a collector that requires the machine's token
  (`ipc.require_token`) without the token sitting in clear in `OTEL_EXPORTER_OTLP_HEADERS`. Without a usable token
  it prints nothing on stdout and exits 1. A session never runs it: the owner guard refuses it (`keys`) and the MCP
  server's guards refuse every `brain ipc` command (`wi-brain-local-ipc-auth`).
