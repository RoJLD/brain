section: Added

- Graph templates as layers (`wi-brain-graph-templates`): the catalogue `templates/layers/<name>.yaml` (work,
  decisions, records, lessons, ideas, research, data, code, docs_tests, features, operations, fleet, rules, delivery:
  types, edges with their endpoints, statuses, mode, commands, views, checks, GitNexus projection, fictitious
  examples), `research_graph.layers` (parse, resolve with what a layer requires, compose, render, add by a plan),
  the command `layers [show | compose | add [--write] | propose]`, `init --layers`, and two optional schema.yaml keys:
  `templates:` (the layers and versions that composed it) and `endpoints:` (the `{from, to}` pairs each edge type
  allows), which `check` now verifies. A schema without them is read and checked as before; the default schema is
  unchanged.
