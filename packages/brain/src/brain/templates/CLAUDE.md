# {owner}'s brain — rules for working in this repo

This private repo is {owner}'s personal brain: the rules for every project (`rules/global.md`, config.json `rules`),
the backlog graph (`notes/graph`), the decision log (`notes/decisions.md`), the journal (`notes/journal.md`), the
records (`records/`) and the memory notes (`memory/`). The engine is the `brain` command, installed at the tag
config.json `engine.pin` names; its Claude Code hooks reach sessions through this repo's local marketplace
(`.claude-plugin/`, `plugins/`), rendered from `source/packs.yaml` by `brain sync`.

- Backlog edits go through `brain item add|set|close|link`, journal entries through `brain journal add`, ADRs through
  `brain adr new`, questions to {owner} through `brain decision ask|answer|ack`; `brain refresh` regenerates the views
  and checks. The generated files (`notes/kanban_graph.md`, `notes/roadmap_graph.md`, `notes/decision_queue.md`,
  `_generated_*.yaml`, `.claude-plugin/`, `plugins/`) are never edited by hand.
- No secret, no session transcript in this repo.
