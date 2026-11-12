section: Added

- `brain schema diff --against <tag>` (`wi-brain-schema-diff`): what a change of the JSON Schemas and the graph
  stores' `schema.yaml` narrows (a property removed, a field newly required, an enum or a type narrowed, a bound
  tightened, `additionalProperties` closed, a node type, an edge type or a status removed), and whether the PR's
  `Compat:` line resolves it (`Compat: migration <id>` with the format's `v` bumped and its fixture, or
  `Compat: breaking <adr-id>`). The scout (`brain audit --diff`) shows it as a `schema.narrowed` line: an info line by
  default, NEW under the new optional config.json key `audit.schema_diff_strict`. CI's advisory `schema-diff` job runs
  it on every pull request (docs/formats.md, « The schema diff »).
