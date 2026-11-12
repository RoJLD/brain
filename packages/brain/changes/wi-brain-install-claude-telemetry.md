section: Added

- Claude Code's OTLP export settings come from the brain, never typed by hand (`wi-brain-install-claude-telemetry`):
  config.json `adapters.claude.telemetry` (`enabled`, `endpoint`, `protocol`, `exporters`, `env`, `headers_helper`),
  rendered by `brain ipc claude-settings [--json]` and added by `install.ps1`'s new telemetry step to
  `~/.claude/settings.json`: `env` `CLAUDE_CODE_ENABLE_TELEMETRY` and `OTEL_*`, and `otelHeadersHelper` = `brain ipc
  otel-headers` once config.json `ipc.require_token` names the collector. Additions only (a key already there with
  another value is kept and said), a plan then `-Apply`, `settings.json.bak` kept; the helper off loopback or with
  grpc, and any `*HEADERS*` variable, are refused. `brain health ipc` fails when the collector requires the token and
  Claude Code's export is on without the helper (docs/mcp.md, « Claude Code's export settings »).
