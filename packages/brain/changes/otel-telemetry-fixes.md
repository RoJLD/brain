section: Fixes

- The sovereign collector no longer stores the account with every record (`wi-brain-otel-telemetry`; the owner's
  decisions ST-7 and ST-8): its processors drop `user.email`, `user.account_uuid`, `user.account_id` and
  `process.owner` from the records' attributes and their resource, and a tool's parameters and a failure's error text
  (its class, `error_type`, stays), in every pipeline; an MCP or a skill call keeps its names. A running collector
  takes the new configuration once `brain bundle apply sovereign` has written it and `brain down otel-collector`,
  `brain up otel-collector` have restarted it; `brain telemetry` drops the same attributes from the files written
  before.
