# brain — the engine

The public engine of the Brain: the code that keeps a person's or a team's work state, decisions and backlog in git,
readable by people and by agents. Each person keeps their own data (rules, decisions, backlog, memory) in a private
repo of their own; this repo holds only code, templates and examples.

It holds one package today, **`research-graph`** (module `research_graph`): a typed, layered knowledge graph kept as
YAML in a git repo, with a loader that validates it, `sync` that derives nodes from the repo (decision logs,
experiments), queries over the work layer (backlog, milestones, decisions waiting for the owner), its history from git,
and generated markdown views (a kanban board and a roadmap). The `brain` command (`brain sync`, `check`, `refresh`,
`decision pending`) and a quant research platform both run it, pinned by tag.

## Install

Python 3.10 or later; it depends on networkx and PyYAML.

```bash
pip install "research-graph @ git+https://github.com/RoJLD/brain.git@v0.1.0"
```

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

`examples/projects.yaml` is a registry for the `brain` command: one entry per project, each with its own store.

## A store

```
notes/graph/
  schema.yaml          owner, node_types, edge_types, statuses, layers (layer -> types), status_by_type, levels
  nodes/*.yaml         flow-style nodes: - {id: wi-x, type: WorkItem, status: todo, title: "...", props: {...}}
  nodes/_generated_*   written by sync (decision, experiment and hypothesis stubs); never edited by hand
  edges/*.yaml         - {from: wi-x, to: ms-y, type: part_of}
  edges.yaml           hand-written edges, then the block sync regenerates (# --- auto-derived ...)
```

The schema belongs to the store: each store (a project, a person's brain, a team) declares its own types, statuses and
layers, and its `owner`, the person or team who decides for it. Every path is given on the command line; nothing is
written outside the store, the repo root and `--out`, and the engine keeps no state between calls.

## Commands

`research_graph [--store notes/graph] [--repo-root .] [--overlay <store> ...] <command>`, or `python -m research_graph`.

| Command | What it does |
|---|---|
| `init [--owner NAME] [--examples]` | A new store from the templates (above). |
| `build` | Load and validate the store (with its overlays). |
| `check` | Coverage (a node per dated heading of the decision logs, anchors that resolve), wiring and code-layer structure; advisories (consistency, stale generated views). Exit 1 on a problem. |
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
```

## Tests

```bash
pip install -e ".[test]"
pytest
```

`tests/test_golden.py` pins the outputs of the commands their users run (`tests/golden/`): each case compares the exit
code, stdout, stderr and the files written, byte for byte. `RESEARCH_GRAPH_MODULE` names the module under test
(default `research_graph`); `RESEARCH_GRAPH_GOLDEN=update` rewrites the files, for a change of behaviour that is meant
(review the diff).

## Releasing

A release bumps `__version__` in `src/research_graph/__init__.py`, adds its `CHANGELOG.md` heading, and is tagged
`vX.Y.Z` on the merge commit. The version must change with every tag: pip reinstalls a git-pinned dependency only when
its version differs (CI checks that the tag matches). Consumers move by their pin.

## License

MIT
