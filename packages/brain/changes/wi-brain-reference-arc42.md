section: Added

- The technical reference's arc42 skeleton (`wi-brain-reference-arc42`, [docs/views.md](docs/views.md), « The
  technical reference »): `docs/reference/README.md` now holds the twelve arc42 sections, each from its source in the
  graph, every statement with its status and its id: goals and the pending milestones' triggers, constraints from the
  rules (the decisions that set them, what enforces them), context from the registry, the solution strategy and its
  key decisions, the building blocks (the module pages), the runtime view (hooks, workflows, skills, plugins, MCP
  servers), the deployment view (the project's stacks), the specs in force, the decisions by module, quality as each
  milestone's trigger, its items and their tests (the goals with no test counted), risks and debt (blocked items, debt
  items, open lessons, open questions), and a glossary. The prose a person writes lives in `docs/reference.yaml`
  (`schemas/reference.schema.json`, a new format registered with the others: `goals`, `strategy` and `glossary`
  required; a short intro per section and per module optional); a required field missing fails `brain reference`
  (nothing written) and `brain check` once the reference is kept. The public render takes the goals, strategy and
  glossary of the public repo's own `docs/reference.yaml`.
