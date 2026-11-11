# The module map

A brain that builds a platform module by module keeps, in its store, the registry of those modules
(`notes/graph/modules.yaml`). Each open item then names its module: `props.module`, its primary, one; and
`props.modules_secondary`, a list or a string of ids separated by commas. `brain sync` writes the view `notes/modules_graph.md` (`modules_graph.md` beside the store's board when that is not in notes/: a project's second store, a project that shares its root) from both, and `brain check`
warns about an open item the map does not place (`brain.modules`, zero token). A store that reads no registry (its
own `modules.yaml`, or the one `config.json` `modules.store` names, below) is not concerned.

## The registry

```yaml
- {id: P2, name: kettle-core, brick: P, phase: MVP, status: tree}
- {id: P12, name: kettle-meter, brick: P, phase: V1.5, status: proposed, lab: now, since: 2026-08-01,
   note: "Weigh and time, split from P2."}
```

- `phase`: the product's phase the platform's tree gives the module (MVP, V1.5, V2...).
- `status`: `tree` for a module of the platform's tree, `proposed` for one the brain proposes and the owner has not
  taken yet.
- `lab`: the brain's own phase.
- `since`: the day a proposed module was proposed; for a wanted module of the map, the day it was wanted (its 90
  days count from it, below).
- `note`: free text.

## A registry kept in another store

A programme that spans several projects may keep the registry in its own store rather than in each project's: a
store without its own `modules.yaml` then reads the one `config.json` names (since 0.3.2,
`wi-brain-module-registry-import`):

```json
{"modules": {"store": "programme"}}
```

`modules.store` names a store of the projects registry (`projects.yaml`, as `brain check --all` reads them): its
label `<project>:<store relative to its root>` (`programme:programme/graph`), or its project's name (that project's
first store that keeps a `modules.yaml`). Only the stores under `config.json`'s folder read it: another project's
store, at its own root, never does. The stores that read it keep every check of this page against that registry, and
their view names it (``the registry `programme:programme/graph/modules.yaml` ``); a worktree of the checkout that
holds `config.json` reads it the same way. Without the key a store reads only its own registry, as before; a key that
names no store keeping one is a warning of `brain check` and the reason `brain modules` gives when it finds no
registry.

Turning the key on is the owner's opt-in to the module checks on those stores: each store under `config.json`'s
folder that keeps no registry is then checked like a store that keeps one (an open item with no module is a warning
of `brain check`, an exit 1 of `brain modules --check`), and its view is written by the next `brain sync`; until then
that view is stale, an error of `brain check` on the default branch under `views.strict`. The technical reference
(`brain reference`) reads the same registry.

## An imported registry

The registry can be a read copy of the platform's own documents, which stay the source of truth: an agent session
reads them (the engine never does) and writes the entries' document fields, with the reference and the date of each
document read. The engine validates what the import wrote, generates the counts and says what changed:

```yaml
- {id: P2, name: kettle-core, brick: P, phase: MVP, status: tree, definition: "Boil and pour",
   declared: [K1], divergences: ["the placement sheet says V2, the annex MVP"],
   source: [{ref: "the vision, annex A", date: 2026-10-20}, {ref: "placement sheet", date: 2026-10-24,
             fields: [phase, status]}],
   imported: 2026-11-11,
   lab: now, note: "Hand fields: the import never writes them."}
```

- The document fields, which only an import writes: `name`, `brick`, `phase`, `status` (`tree` or `proposed`),
  `placement` (the platform's own word on where the module stands: planned, out of the roadmap, conditional...),
  `definition`, `declared` (the dependencies the documents declare, as module ids), `divergences` (what the
  documents disagree on, one text each), `source` (the documents read: each a `ref` and its `date`, and optionally
  the `fields` it gave) and `imported` (the day of the import). Every other field (`lab`, `since`, `note`, ...) is
  written by hand and never touched by an import.
- An entry is imported when it carries the import's shape: `source` a list of mappings, or `imported` a day (a
  date, or a timestamp: its day). `brain modules --check` (exit 1) and `brain check` (a warning) then refuse: a
  missing `name`, `brick` or `phase`; a `status` other than `tree` or `proposed`; no `source`, a source with no `ref`
  or no `date`, a document dated after the import; no `imported`; a `fields` entry that is not a document field
  (`source` and `imported` are not); a `placement` or `definition` that is not a text; a `declared` that is not a
  list of ids the registry knows; `divergences` that are not texts; an id given twice. A hand entry is never checked
  this way, even one whose own `source` is a text: a registry written by hand passes as before.
- The view gains, for a registry with imported entries only, the counts generated from it (in the tree, proposed,
  in all, and by brick: no count is ever written by hand), the documents read with their dates, and the divergences
  the import reported. The brain never settles a divergence: the owner corrects the documents, and a new import
  brings the correction.
- `brain modules --diff [REF]` says what changed since the registry's version at a git ref (default `HEAD`: the
  last committed import): the counts on both sides, the modules added and removed, each document field changed and
  each hand field changed (`<id>.<field>: <old> -> <new>`), and the modules whose sources or day of import alone
  changed (their ids on one line). A hand field changed by an import is an import that went too far. A ref that is
  no commit of the registry's repository (a typo, no repository) or a registry there that does not parse ends the
  command with its reason, never as « all new »; a commit that does not hold the registry yet is « all new ».
  `--json` gives an object: `registry`, `ref`, `added`, `removed`, `drive` (the document fields' lines), `hand`,
  `provenance` (the ids), `before` and `after` (the counts; `before` null when the commit holds no registry). With
  `--check`, the report comes first, then the check; with `--check --json`, one object `{diff, problems}`.

`brain modules --json` gives `counts` (`tree`, `proposed`, `all`, `bricks`), `imported` (how many entries) and
`registry_problems`; `brain modules --check --json` lists the imported entries' problems, then the map's (below),
then the open items'.

## The map of realisations

Beside the document fields, an entry can say who realises the module and where (since 0.3.2,
`brain.modulemap`). These fields are written by hand, by PR, and never by an import:

```yaml
- {id: P2, name: kettle-core, brick: P, phase: MVP, status: tree,
   wanted: true, ai: false, capabilities: [backlog], depends_on: [K1], uses: [P12], map_review: proposed,
   realized_by: [{project: lab, kind: lab, what: "the kettle bench", paths: [bench/], ref: HEAD, licence: MIT,
                  state: running, contract: kettle/v1, ships_in: lab, retire: "once the product ships it"},
                 {project: kettle, kind: product, what: "the kettle", state: pr-open, ships_in: kettle}]}
```

- `wanted`: whether the owner wants the module (set `since` the day it is wanted).
- `capabilities`: the engine's capabilities (`tiers.yaml`, [tiers.md](tiers.md)) that realise it in a brain.
- `depends_on` and `uses`: the modules it needs (hard) and the ones it uses when they are there (soft), ids of the
  registry, classified by hand from the documents' `declared`; a declared one in neither counts as soft.
- `ai`: the module is AI (a model).
- `realized_by`: each realisation, with `project` (a project of the projects registry, read-only ones included),
  `kind` (`lab`, `product`, `brain`, or `app` for an application of the owner's software hub), `what`, `paths` (in
  the project's repo) and the git `ref` they are checked at (default `HEAD`), `licence`, `state` (`planned`,
  `building`, `pr-open`, `partial`, `built`, `running`, `retired`), `contract` (what it exposes), `ships_in` (the
  distribution that ships it) and, for a lab realisation, `retire` (when it gives way).
- `map_review`: `proposed` while the map of the entry waits on the owner's review, `validated` once reviewed.

The format is the engine's `schemas/modules.schema.json` (a registered format, [formats.md](formats.md)). Only an
entry that carries `realized_by` or `map_review` is concerned, whatever other fields it holds: a registry written
before the map, where a hand entry may hold its own `wanted` or `uses`, is checked and rendered as before. On the store that keeps the registry, `brain modules --check` (exit 1) and `brain check` (a warning)
refuse:

- an entry the schema refuses (a type, a `kind` or `state` it does not know, a realisation without `project`, `kind`
  or `state`); a realisation's unknown key is a newer brain's: a note in read mode, an error in strict mode (CI);
- a `depends_on` or `uses` module the registry does not know, a module in both;
- a capability not in `tiers.yaml`;
- a project not in the projects registry;
- a path missing at its ref, when the project's checkout is on this machine (a project without one is not checked);
- a wanted module with no realisation (a retired one does not count) and no open item that builds it, in any store
  that reads the registry.

They warn, never fail, of a wanted module with no item done or open 90 days after its `since`: dormant, to put back
to sleep. The view gains, when an entry carries the map, the realisations (one row each, with the entry's review),
the map's gaps (a wanted module with no realisation, a lab realisation with no target one, a product phase, MVP or
Vn, with no product realisation for a module of the tree) and the declared dependencies still to classify;
`brain modules --json` gains `map` (each entry's map fields) and `map_problems`.

## An item's module

```bash
brain item set wi-x props.module=P2 "props.modules_secondary=P12, M4"
brain item set wi-y props.module=none "props.module_reason=the brain's own process, outside the tree"
```

`brain check` warns, and `brain modules --check` lists and exits 1, when:

- an open item has no `props.module`;
- its module is `none` with no `props.module_reason`;
- its module, or one of its secondary modules, is not in the registry;
- a secondary module repeats the primary.

## The features' and the done items' modules

The technical reference reads by module what each module does (its features) and what was delivered in it (its done
items), so those carry a `props.module` too (since 0.3.2, `wi-brain-module-backfill`):

```bash
brain features set feat-x module=P2
brain item set wi-old props.module=P2
```

`brain check` warns about them, and `brain modules --check` lists them as warnings without counting them in its exit
code (a warning, never a failure):

- the features, then the done items, with no `props.module`: one line per kind, with how many and the first ten ids;
  once a brain has placed them all, such a line names a new one;
- one whose module is `none` with no `props.module_reason`, or is not in the registry.

`brain modules --json` gives `features`, `features_unplaced`, `done_items`, `done_unplaced` and `warnings`;
`brain modules --check --json` keeps the open items' problems only, as before. The public render of `FEATURES.md`
(`brain features render` into a public repo) never shows the Module column: the module ids are the owner's
platform's. A public `FEATURES.md` an earlier engine rendered with that column is then stale: `brain sync` (or
`brain features render --write`) renders it again.

## The view

`notes/modules_graph.md` (`brain modules` prints it, `--write` writes it, `brain sync` writes it) gives:

- how many features and done items are placed (when the store has any);
- a table of the modules by brick, each with its phase, its status, the items done and open with it as primary, and
  the open items with it as secondary;
- the gaps:
  - a module with no item done or open;
  - a proposed module with none, to put back to sleep 90 days after its proposal;
  - a module an item names that the registry does not know;
- for an imported registry, the counts by brick, the documents read and the divergences between them;
- per module, its open items and the open items that have it as secondary;
- the items outside the tree, with their reason.

The view holds no date of its own, so it changes only when the registry or the items change.

The view is a generated file, like the kanban: `.gitattributes` sends it to the brain's merge driver
(`notes/modules_graph.md merge=brain`, a line `brain init` writes), which keeps one side of a merge and marks it
for `brain refresh`. Stale, it is a warning of `brain check` on the default branch (an error under `config.json`
`views.strict`) and one `views:` line on another branch; `brain views --write` writes it there after each merge, and
under `views.strict` `brain modules --write` refuses an engine other than the pin ([views.md](views.md)).
