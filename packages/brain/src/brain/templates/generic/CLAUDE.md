# {owner}'s brain — rules for working in this repo

This private repo is {owner}'s personal brain: the rules for every project (`rules/global.md`, config.json `rules`),
the backlog graph (`notes/graph`), the decision log (`notes/decisions.md`), the journal (`notes/journal.md`), the
records (`records/`) and the memory notes (`memory/`). The engine is the `brain` command, installed at the tag
config.json `engine.pin` names; its Claude Code hooks reach sessions through this repo's local marketplace
(`.claude-plugin/`, `plugins/`), rendered from `source/packs.yaml` by `brain sync`.

- Backlog edits go through `brain item add|set|close|link`, journal entries through `brain journal add`, ADRs through
  `brain adr new`, questions to {owner} through `brain decision ask|answer|ack`; `brain sync` regenerates the views
  and `brain check` checks (`brain refresh` does both from a worktree, `brain refresh --on-main` in the main
  checkout). The generated files (`notes/kanban_graph.md`, `notes/roadmap_graph.md`, `notes/decision_queue.md`,
  `_generated_*.yaml`, `.claude-plugin/`, `plugins/`) are never edited by hand.
- Reading goes through the read commands too, not the files: `brain item show <id>`, `brain items` (filters),
  `brain adr show <adr-id|rule-id>`, `brain spec show <spec-id> --section N`, `brain journal last [N]`.
- After a merge of the default branch into a branch, `brain refresh` regenerates the views the merge driver kept
  from one side (`.gitattributes` `merge=brain`, `brain merge-driver install --apply`), then commit.
- Every tracked file has a side in `boundary.yaml`. Code, tests and their fixtures (`src/`, `tests/`, `fixtures/`)
  may be published one day: they name no one (an invented owner in the tests), and `brain check` refuses a
  private term, a secret, an e-mail address or a home folder in them.
- No secret, no session transcript in this repo.
