# The registry of the graphs

A project's knowledge sits in several graphs: the layers of its graph stores (work, decisions, records, features,
code, docs and tests, lessons, and layers of its own), the overlays it reads from other repos, the code index of its
repos, the documentation graphs it reads from other projects, and the files some layers are generated from. Each had
its own command (`research_graph layers`, `brain projects`, `brain index`, `brain docgraph join`) and none listed them
all. `brain graphs` puts them in one list, per project or for every project, at zero token. It writes nothing: no
store, no record, no cache. `brain.graphs`, `wi-brain-graph-registry`.

```bash
brain graphs                      # the project at the current folder
brain --project lab graphs --json
brain graphs --all                # every registered project, then the projects the brain only reads
```

It exits 0: it is a report. A store that does not parse, a missing file or a code index declaration this machine
cannot serve is shown on its row and never stops the list. `--project` and `--all` together are refused.

## What it lists

| Section | Kind | What it says | Read from |
|---|---|---|---|
| store | `intention` | each layer of each graph store of the project, then each overlay (`read_only`) | the store's `schema.yaml`, `nodes/`, `edges.yaml`, `edges/`, the layer catalogue, git |
| code index | `federated` | each repo of `code_index:`, once per backend this machine has or that recorded it, and its state against the branch head (`OK`, `STALE`, `NOT INDEXED`, `ERROR`) | the backends' records under `$BRAIN_HOME`, git; no service is called |
| docgraph | `federated` | each documentation graph under the root's `docgraph/`, its node and edge counts and the commit it describes; a read project's pinned copy goes under that project with `--all` | `docgraph/*.json` (`brain docgraph pin`) |
| source | | the files beside the graph: decision logs, journals, ledgers, stacks, schedules, then, for the project that owns its root, `records/`, `memory/`, the neutral source (rules, procedures, MCP servers) and `config.json` | the registry entry, the root |

### A store's layers

- **Which layer.** A node type is in the layer the store's own `schema.yaml` `layers:` names, else in the catalogue's
  layer that holds it (`research_graph layers`), else in no layer (`name` null, shown `(no layer)`). An edge counts in
  the catalogue's layer that declares its type when the store holds that layer, else in its source node's layer.
- **Version.** `version` is what the schema's `templates:` recorded (`null` when it did not), `catalogue_version` the
  engine's catalogue's, so a store behind the catalogue shows both.
- **Written or generated.** `generated` when every file that holds its nodes and edges is a `_generated_*` file
  (`brain sync` rewrites them), `written` when none is (commands write them: `brain item`, `brain lesson`...), `mixed`
  otherwise; `generator` is the catalogue's generator for the layer, else `brain sync` (empty for a written layer).
- **Freshness.** The last commit of the layer's files (`commit`, `day`) and whether one of them has uncommitted
  changes (`uncommitted`); `null` when the store is not in a git checkout.
- **Entries.** `query`: the catalogue's commands for the layer; `impact`: `research_graph impact <id>`, and `brain
  impact --diff` for the code layer; `read_by`: the engine's commands and cockpit panels that read it now.
- **Planned.** The catalogue's layers the store does not hold, each with the command that adds it
  (`research_graph --store S layers add NAME`, a plan first).

## The `--json` keys (v 1)

A public contract: keys are only added, never renamed or removed; a change of a key's meaning is `v` 2. A reader keeps
a key it does not know, and shows a layer, kind, mode, backend or state it does not know as it is.

```text
{v, scope: project|all, projects: [
  {name, title, root, access: write|read, found,
   stores: [{path, kind: intention, read_only, error, nodes, edges,
             layers: [{name, catalogue, version, catalogue_version, title, mode: written|generated|mixed, generator,
                       files, types: {type: n}, nodes, edges: {type: n}, edge_count,
                       freshness: {commit, day, uncommitted} | null, query, impact, read_by}],
             planned: [{name, catalogue_version, title, add}]}],
   code_index: [{repo, backend, kind: federated, state, why, query, impact, read_by}],
   docgraph: [{name, path, kind: federated, read_only, ok, error, ref, nodes, edges, read_by}],
   sources: [{name, kind: files|inline, paths, exists, files, freshness, read_by}]}]}
```

Paths are relative to the project's root (a store outside it keeps its full path). A project the brain only reads
(`access: read`, with `--all`) has no store, code index or source: only its pinned documentation graph, when one is
kept.

## What it does not do yet

- Search across the layers (`brain graphs search`), the cockpit's Graphs tab and the graph RAG (`brain context`) read
  this list; they are not built. Each one that ships adds itself to `read_by`.
- A layer planned but not in the catalogue yet (a layer the owner's backlog plans) is not listed: the list says what
  the engine can add now.
