section: Added

- `brain project new` plans what the answers propose beyond the registry (`wi-brain-project-wizard-pack`, its third
  slice): the typology packs its kinds meet and their parts (each pack's procedures, MCP servers and the guards it
  turns on, the core's hooks, the template's CI workflows) and its judgement (clauses of done, one-way doors, roles,
  gates by stage), written by `brain init` into the project's `CLAUDE.md` as a section « What it produces »; then
  `--apply` runs, after `brain init`'s files, `brain --root DIR typologies propose NAME --apply`, `brain --root DIR
  render --target claude --write` and `brain --root DIR --project NAME render --target agents --write` (its
  `AGENTS.md`), each logged as the owner's step in the setup ledger (`via: project-new`); a step that fails does not
  stop the next and the run exits 1 naming it. A folder's own `CLAUDE.md` or `AGENTS.md` is kept, and the plan says
  so. In a folder that holds the brain already the parts are planned against it and never run (`--apply` exits 2
  while a step is left, and says so). `brain typologies propose` no longer lists a standards profile the project
  meets through a sub-profile (a `cli` selection meets `software`).
