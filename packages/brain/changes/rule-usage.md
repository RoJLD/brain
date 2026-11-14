section: Added

- `brain usage --kind all|skill|rule|command|script|mcp|tool|hook|guard|plugin|scheduled` (`wi-brain-rule-usage`):
  the usage counters of every kind of tooling, keyed by a stable tool id (`brain.toolids`: a Skill call, a slash
  command, a Read of the SKILL.md and an Agent's prompt naming it are one skill; a transcript's MCP tool and the
  OpenTelemetry export's are one). Per tool: calls, sessions, projects, the token cost that can be attributed, the
  last use; a skill, rule, brain command or schedule unused for 30 days is marked « retire or merge » against an
  inventory, an MCP tool, hook or plugin once seen and silent since. A brain command keeps only the registry's
  subcommand, never an argument. The transcripts stay the first source (the token ledger's scanner 4 adds each row's `tooling` and
  `refused`, so the rows are rescanned once); the export adds the hooks' runs and durations, the tools' durations and
  the rejected calls when the collector runs; the guards ledger names each refusal's guard, joined by tool use id.
  `--json` carries the replay of the sources against each other (`misses`). `brain perf --usage` reads brain
  commands through the same parser.
