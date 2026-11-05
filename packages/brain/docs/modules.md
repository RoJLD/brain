# The module map

A brain that builds a platform module by module keeps, in its store, the registry of those modules
(`notes/graph/modules.yaml`). Each open item then names its module: `props.module`, its primary, one; and
`props.modules_secondary`, a list or a string of ids separated by commas. `brain sync` writes the view `notes/modules_graph.md` (`modules_graph.md` beside the store's board when that is not in notes/: a project's second store, a project that shares its root) from both, and `brain check`
warns about an open item the map does not place (`brain.modules`, zero token). A store without `modules.yaml` is not
concerned.

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
- `since`: the day a proposed module was proposed.
- `note`: free text.

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

## The view

`notes/modules_graph.md` (`brain modules` prints it, `--write` writes it, `brain sync` writes it) gives:

- a table of the modules by brick, each with its phase, its status, the items done and open with it as primary, and
  the open items with it as secondary;
- the gaps:
  - a module with no item done or open;
  - a proposed module with none, to put back to sleep 90 days after its proposal;
  - a module an item names that the registry does not know;
- per module, its open items and the open items that have it as secondary;
- the items outside the tree, with their reason.

The view holds no date of its own, so it changes only when the registry or the items change.

The view is a generated file, like the kanban: `.gitattributes` sends it to the brain's merge driver
(`notes/modules_graph.md merge=brain`, a line `brain init` writes), which keeps one side of a merge and marks it
for `brain refresh`.
