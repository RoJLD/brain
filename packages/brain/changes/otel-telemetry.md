section: Added

- `brain telemetry summary` and `brain telemetry status` (`wi-brain-otel-telemetry`): Claude Code's OpenTelemetry
  export as the sovereign collector stored it, read at zero token with the standard library (`brain.otel`, rotated
  files included). The summary gives, per UTC day, model and session, the tokens by type, the cost, the API requests,
  errors and retries, then the tool decisions by decision and source, the tools' failures and error classes and the
  hooks' p50 and p90 (`--days`, `--session`, `--top`, `--json`). The status says whether the export is on, whether the
  collector's health endpoint answers (bounded) and how old each signal's last record is: exit 1 when the export is
  on and the collector is down or receives nothing.
