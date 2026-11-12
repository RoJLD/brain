# Changelog — research-graph

The repo's two distributions share one tag series: a tag `vX.Y.Z` is both `research-graph` X.Y.Z and `brain` X.Y.Z
(`packages/brain/CHANGELOG.md` for the brain command).

## 0.4.0 — 2026-11-12

### Added

- Graph templates as layers (`wi-brain-graph-templates`): the catalogue `templates/layers/<name>.yaml` (work,
  decisions, records, lessons, ideas, research, data, code, docs_tests, features, operations, fleet, rules, delivery:
  types, edges with their endpoints, statuses, mode, commands, views, checks, GitNexus projection, fictitious
  examples), `research_graph.layers` (parse, resolve with what a layer requires, compose, render, add by a plan),
  the command `layers [show | compose | add [--write] | propose]`, `init --layers`, and two optional schema.yaml keys:
  `templates:` (the layers and versions that composed it) and `endpoints:` (the `{from, to}` pairs each edge type
  allows), which `check` now verifies. A schema without them is read and checked as before; the default schema is
  unchanged.

## 0.3.2 — 2026-11-11

- No change in `research-graph`: the version moves with the shared tag.

## 0.3.1 — 2026-11-10

### Added

- An edge may name another store's node: `--foreign-store LABEL=PATH` (repeatable) gives the stores whose ids the
  edges may name, and `load_store(..., foreign=...)` takes them in Python (`loader.read_foreign`). Such an edge loads
  when one end is the store's own; the other store's node is shown by its id and its label in the board, the roadmap,
  `items`, `item`, `decisions` and `impact` (`wi-x (parent:graph)`), counted in a milestone's progress and as a
  blocker, never listed among the store's own nodes; the board lists an item whose only milestones are other stores'
  under « Part of another store's milestone ». Without the option nothing changes: an edge to an id the store does not
  hold is refused as before (`wi-brain-cross-store-edges`).

## 0.3.0 — 2026-11-10

### Changes

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

## 0.2.8 — 2026-11-09

- No change in `research-graph`: the version moves with the shared tag.

## 0.2.7 — 2026-11-09

- No change in `research-graph`: the version moves with the shared tag.

## 0.2.6 — 2026-11-09

- No change in `research-graph`: the version moves with the shared tag.

## 0.2.5 — 2026-11-04

- `code_layer.symbol_span(tree, symbol)`: the kind, first and last line of a symbol as `find_symbol` finds it,
  decorators and body included (what a change to it touches; `brain impact` without GitNexus).

- **Required props per node type.** A schema may say `required_props: {<type>: [prop, ...]}`: `check` (the loader,
  overlays too) refuses a node of that type without each prop or with it empty (`node les-x: Lesson needs props
  check`); `Schema.missing_props` says which. The store template (`research_graph init`) gains the `Lesson` type (layer
  `lessons`, statuses open, enforced, resolved, regressed, archived; edges `learned_from`, `enforced_by`, `led_to`;
  `trigger`, `anti_pattern` and `check` required), the brain command's lessons registry.

## 0.2.4 — 2026-11-03

- **Fast YAML** (wi-brain-yaml-fast-load): `research_graph.yamlio`, the one helper of every load: `loads` parses
  through libyaml (`CSafeLoader`) when PyYAML has it; `load` reads a file through a per-process memo keyed by (path,
  size, mtime_ns), keeps the data pickled and returns a fresh copy on each read, and checks a file written within 2 s
  of its read against its text's digest. The store loader, the schema, priorities, sync, validate and the history read
  through it. `RESEARCH_GRAPH_YAML_MEMO=0` turns the memo off.

## 0.2.3 — 2026-11-03

- **An anchor of another repo's file resolves in that repo's checkout.** A node may say `repo: <name>`: its anchor's
  path is relative to that repo, not to `--repo-root` (the brain command derives the Doc, Test and Workflow nodes of a
  project's other repos into the store whose CodeRefs name them, since 0.2.2). `check --repo-path NAME=PATH`
  (repeatable) gives a repo's checkout; there `check` reads the anchor, and fails on a missing file with the repo
  named (`anchor file missing: docs/install.md (repo brain)`). Without one, the anchor is not checked and an advisory
  counts them per repo. `repo` names a Repo node, as a CodeRef's repo does. 0.2.2 read every anchor under
  `--repo-root`, so a store holding another repo's nodes failed `check` on each of them. An overlay keeps such an
  anchor relative to its repo.

## 0.2.2 — 2026-11-03

- No change to the graph engine: the version follows the brain command's (one tag series).
- `docs/install.md` (from an empty machine to a brain of one's own, Windows first) and `docs/pilot.md` (the pilot:
  what to try, how to report an issue).
- The licence's metadata in PEP 639 form, the licence unchanged (MIT): `license = "MIT"` (an SPDX expression) and
  `license-files = ["LICENSE"]` replace the `license = { text = "MIT" }` table, which setuptools deprecates and stops
  building from 2027-02-18; the build needs setuptools 77 or later. The wheel's metadata says
  `License-Expression: MIT` and ships `LICENSE`.

## 0.2.1 — 2026-11-03

- No change to the graph engine: the version follows the brain command's 0.2.1 (one tag series).

## 0.2.0 — 2026-11-03

- No change to the graph engine: its version follows the repo's single tag series, now that the `brain` command is
  the repo's second distribution (`packages/brain`, which depends on `research-graph` at the same tag).

## 0.1.1 — 2026-11-02

- Python 3.10: commit dates from git (`%cI`, UTC written `Z`) are read on every supported Python; 0.1.0 failed on
  3.10 in the git-backed views (`items --since`, `item`, `closed`, `events`, `asof`). Caught by the CI's 3.10 job.

## 0.1.0 — 2026-11-02

The graph engine, extracted from the private research repo it was born in, as its own package: the same modules,
store format and outputs, except for the changes below, made so that anyone can run it on their own stores.

- **The store's owner.** `owner` in `schema.yaml` (a person or a team; `g.graph["owner"]` once loaded) replaces a
  name written in the code: `pending` lists the items whose `external_blocker` names the owner under
  `blocked_on_owner` (was `blocked_on_<name>`), adds `owner` to its JSON, and reads `<owner>:` and `(<owner>, <year>`
  as answers in specs. A store without `owner` has nothing blocked on a person.
- **Neutral generated views.** The kanban and roadmap start with `<!-- GENERATED by research_graph ...`; a view whose
  marker names the engine under another module path (`python -m <pkg>.research_graph`) is still a generated view and
  is regenerated in place. The stale-view advisory says `research_graph kanban --write`.
- **`research_graph init [--owner NAME] [--examples]`**: a new store from the templates (schema, empty layers, ADR log;
  with examples, a spec, a milestone, three work items and an ADR), then `sync --write` and `kanban --write`; never
  overwrites. `examples/projects.yaml`: a registry for the `brain` command.
- `export-gitnexus --name` defaults to the repo folder's name, lower case. The staged-module rule of `validate` covers
  every package under `src/`.
- Tests moved with the engine, plus `tests/test_golden.py`: 71 cases recorded from the original module and from the
  package on the same fixtures; every difference reviewed (only the changes above).
- `research_graph` console script; `__version__`.
