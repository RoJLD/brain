# brain — the engine

The public engine of the Brain: the code that keeps a person's or a team's work state, decisions and backlog in git,
readable by people and by agents. Each person keeps their own data (rules, decisions, backlog, memory) in a private
repo of their own; this repo holds only code, templates and examples.

It holds two distributions, released together under one tag series (`vX.Y.Z` is both at version X.Y.Z):

- **`research-graph`** (module `research_graph`, at the repo's root): a typed, layered knowledge graph kept as YAML in
  a git repo, with a loader that validates it, `sync` that derives nodes from the repo (decision logs, experiments),
  queries over the work layer (backlog, milestones, decisions waiting for the owner), its history from git, and
  generated markdown views (a kanban board and a roadmap). A quant research platform runs it, pinned by tag.
- **`brain`** (`packages/brain`): the `brain` command, one command for a personal brain at zero token: records (DDR,
  SR, AR), backlog, decisions waiting on the owner, journal, ADRs, generated views, `brain init` for a new brain, and
  the Claude Code hooks and guards it renders into its owner's own plugin. It depends on `research-graph` at the same
  tag. See [`packages/brain/README.md`](packages/brain/README.md).

## Install

Python 3.10 or later; `research-graph` depends on networkx and PyYAML.

```bash
pip install "research-graph @ git+https://github.com/RoJLD/brain.git@v0.3.1"
pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.3.1#subdirectory=packages/brain"   # the brain command
```

From an empty machine to a brain of your own (Windows first, Linux and macOS): [`docs/install.md`](docs/install.md).
Cutting a release: [`docs/release.md`](docs/release.md). Trying it in the pilot: [`docs/pilot.md`](docs/pilot.md). `packages/brain/installer/stranger_test.py` installs a tag
into a fresh venv, isolated from its caller, and runs that first hour's scenario (the stranger test); with
`--upgrade-from <tag>` it upgrades a brain the tag wrote, then rolls back to the tag on what this engine wrote (the
upgrade test, CI's `compat-prev` job: [`packages/brain/docs/formats.md`](packages/brain/docs/formats.md)).

## Start your own graphs

```bash
research_graph --store notes/graph --repo-root . init --owner "Your name" --examples
research_graph --store notes/graph --repo-root . check
research_graph --store notes/graph --repo-root . kanban          # the board, printed
```

`init` writes a store from the templates in `src/research_graph/templates/`: `schema.yaml` (the vocabulary, with
`owner`), `edges.yaml`, `nodes/work.yaml` and `edges/work.yaml`, and the ADR log `notes/decisions.md` when the repo has
none. With `--examples` they hold a spec, a milestone, three work items and an ADR to read and then replace; without
it the store is empty. It then runs `sync --write` and `kanban --write`, so `check` passes at once. It never
overwrites a store, an ADR log or a spec.

A second store in the same repo keeps its own decision log and views, given before the subcommand (to `init`, then to
every `sync`, `check` and `kanban` of that store):

```bash
research_graph --store prog/graph --repo-root . --decisions prog/decisions.md --views prog init --owner "Your name"
research_graph --store ops/graph --repo-root . --no-decisions --views ops check
```

`--decisions PATH` (repeatable) names the logs the store covers (a file named `scientific_decisions.md` holds SDRs,
any other ADRs; default `notes/scientific_decisions.md` and `notes/decisions.md`), `--no-decisions` none, `--views
DIR` the folder of the board and the roadmap (default `notes`).

`examples/projects.yaml` is a registry for the `brain` command: one entry per project, each with its own store; it
shows a project with two stores, two projects at one root and a project the brain reads and never writes.

## A store

```
notes/graph/
  schema.yaml          owner, node_types, edge_types, statuses, layers (layer -> types), status_by_type, levels
  nodes/*.yaml         flow-style nodes: - {id: wi-x, type: WorkItem, status: todo, title: "...", props: {...}}
  nodes/_generated_*   written by sync (decision, experiment and hypothesis stubs); never edited by hand
  edges/*.yaml         - {from: wi-x, to: ms-y, type: part_of}
  edges.yaml           hand-written edges, then the block sync regenerates (# --- auto-derived ...)
```

A node's `anchor` is `<path>#<fragment>`, the path relative to `--repo-root`. A node that stands for another repo's file
(the `brain` command derives the Doc, Test and Workflow nodes of a project's other repos) says so with `repo: <name>`,
which names a Repo node as a CodeRef's repo does: its path is relative to that repo's checkout.

The schema belongs to the store: each store (a project, a person's brain, a team) declares its own types, statuses and
layers, and its `owner`, the person or team who decides for it. Every path is given on the command line; nothing is
written outside the store, the repo root and `--out`, and the engine keeps no state between calls.

An edge names two nodes of its store, or one of its store and one another store holds: `--foreign-store LABEL=PATH`
(repeatable) gives the stores whose ids the edges may name. Such an edge loads, with one end in the store at least; the
other store's node is shown by its id and its label (`wi-x (parent:graph)`) where it is linked (a blocker, an item or a
sub-milestone of a milestone, counted in its progress, a decision behind a node) and never listed among the store's own
nodes; its title, status and type are read from that store, not validated (its own check does that). Without the
option an edge to an id the store does not hold is refused, as it always was; an id held by no store given is refused
with it.

## Commands

`research_graph [--store notes/graph] [--repo-root .] [--overlay <store> ...] [--foreign-store LABEL=PATH ...]
<command>`, or `python -m research_graph`.

| Command | What it does |
|---|---|
| `init [--owner NAME] [--examples]` | A new store from the templates (above). |
| `build` | Load and validate the store (with its overlays). |
| `check [--repo-path NAME=PATH ...]` | Coverage (a node per dated heading of the decision logs, anchors that resolve), wiring and code-layer structure; advisories (consistency, stale generated views). An anchor of another repo's node resolves in the checkout `--repo-path` gives for it; without one it is not checked (an advisory). Exit 1 on a problem. |
| `sync [--write]` | Derive decision stubs from `notes/decisions.md` (ADR) and `notes/scientific_decisions.md` (SDR), experiment, hypothesis, verdict, sweep and exploration stubs from `experiments/` and `results/`, and the lineage edges; print them, or write `nodes/_generated_*.yaml` and the auto-derived block of `edges.yaml`. |
| `kanban [--write] [--out F]` | The work layer as a markdown board (`notes/kanban_graph.md`); `--write` also writes the roadmap. |
| `roadmap [--write] [--json] [--markdown]` | Milestones: status, trigger, reached, the items that move each (`notes/roadmap_graph.md`). |
| `items`, `item <id>`, `closed`, `events`, `asof <day>` | The backlog with filters (`--status`, `--all`, `--priority`, `--repo`, `--prop`, `--text`, `--since`), one node with its links and git history, closed items by date, changes from git, the backlog on a past day. `--json` on each. |
| `pending [--json]` | Decisions waiting for the owner: items' `props.open`, unanswered spec questions, items whose `external_blocker` names the owner, proposed specs. |
| `priorities proposal`, `priorities apply [--write]` | Priority proposals (`props.priority_proposed`) and applying the validated ones. |
| `work-frontier`, `blocked`, `milestone <id>` | What can start now, what is blocked and by what, a milestone's progress and critical path. |
| `frontier`, `gated`, `provenance <id>`, `impact <id>`, `decisions <id>`, `layer <name>` | Research-layer queries, cross-layer impact, the decisions behind a node. |
| `code <id>`, `code-check [--platform-root D] [--json F]` | CodeRef nodes behind a node; CodeRefs whose file or symbol is gone in the sibling checkouts. |
| `export-gitnexus [--out F] [--mode single\|typed] [--push URL] [--name N]` | The graph as a payload for a GitNexus sidecar (`--name` defaults to the repo folder's name). |

A generated view starts with a `<!-- GENERATED by research_graph ...` marker; a file without it is never overwritten.
A view written under an older module path (`python -m <pkg>.research_graph`) is still recognised as generated.

## Python

```python
from research_graph.loader import load_store, apply_overlay, ValidationError
from research_graph.model import LayeredGraph
from research_graph import query

g = load_store("notes/graph")          # a networkx.DiGraph, typed and validated; g.graph["owner"] from schema.yaml
LayeredGraph(g).work_frontier()
query.list_items(g, statuses=["todo", "doing"])

from research_graph.loader import read_foreign
g = load_store("notes/graph", foreign=read_foreign([("parent:graph", "../parent/graph")]))  # edges to its ids load
```

Another store's node carries `foreign` (its store's label) and `foreign_type`, and no `type`:
`research_graph.model.kind(g, id)` gives the type of either, `label(g, id)` the name a view shows.

## Tests

```bash
pip install -e ".[test]"
pytest
```

`tests/test_golden.py` pins the outputs of the commands their users run (`tests/golden/`): each case compares the exit
code, stdout, stderr and the files written, byte for byte. `RESEARCH_GRAPH_MODULE` names the module under test
(default `research_graph`); `RESEARCH_GRAPH_GOLDEN=update` rewrites the files, for a change of behaviour that is meant
(review the diff).

The brain command's tests run against both packages from this checkout (`packages/brain/README.md`, Tests):

```bash
pip install -e . && pip install --no-deps -e packages/brain && pip install pyyaml pytest pytest-xdist
pytest packages/brain -n auto
```

## Releasing

A release bumps `__version__` in `src/research_graph/__init__.py` and `packages/brain/src/brain/__init__.py` to the
same X.Y.Z, moves the `research-graph @ ...@vX.Y.Z` pin in `packages/brain/pyproject.toml`, adds the heading of each
`CHANGELOG.md`, and is tagged `vX.Y.Z` on the merge commit. The version must change with every tag: pip reinstalls a
git-pinned dependency only when its version differs (CI checks that the tag, both versions and the pin agree).
Consumers move by their pin.

## License

Each package has its own licence:

- `research-graph` (`src/`, and everything outside `packages/brain`): the MIT License (`LICENSE`).
- `brain` (`packages/brain`): the Business Source License 1.1 from 0.2.2 (`packages/brain/LICENSE`, and `NOTICE`, the
  credit to keep). Its Additional Use Grant allows any use for your own work and reuse in your own products, with a
  visible credit to Brain and its author and the NOTICE kept; offering it to third parties as a hosted or managed
  service needs a commercial licence. Each version changes to the Apache License 2.0 four years after its release.
  `brain` 0.2.0 and 0.2.1 were released under the MIT License and stay under it.
