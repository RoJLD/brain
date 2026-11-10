section: Changes

- **A store's decision logs and views folder, given** (wi-brain-shared-root-projects): two stores of one repo can each
  keep their own. `--decisions PATH` (repeatable, before the subcommand) names the decision logs a store covers,
  relative to `--repo-root`: `check` wants an SDR/ADR node per dated heading of each, `sync` writes the missing
  stubs, anchored at the log's real path (`prog/decisions.md#2026-11-05-x`); a file named `scientific_decisions.md`
  holds SDRs, any other ADRs. `--no-decisions`: the store covers none. `--views DIR`: the folder of the board and the
  roadmap, where `kanban --write` and `roadmap --write` write them and `check` flags them stale. `init` writes its ADR
  log at the first ADR log given (none with `--no-decisions`) and runs `sync` and `kanban` with the same options.
  Without them nothing changes: notes/scientific_decisions.md and notes/decisions.md, views in notes/. A node now
  covers the log its anchor names (by path, case folded), not any log of the same file name; a log outside
  `--repo-root` is refused (an anchor is a path inside it), a views folder may be anywhere. `sync --write` empties
  `_generated_decisions.yaml` once no log derives a stub (the logs are in git: none left is authoritative), where it
  kept the old stubs.
