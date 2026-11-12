# The documentation graph

A brain whose store has the `Doc` type (`brain sync` writes its Doc, Test and Workflow nodes, `brain.links`) also
keeps a documentation dependency graph, at zero token (`brain.docsgraph`, wi-brain-docs-graph): which docs exist,
what each cites, which ones depend on others without citing them, and which ones to re-read because something they
cite changed after them.

## The catalogue

Every doc file a Doc node belongs to (its sections are the Doc nodes: a README, `docs/**`, a runbook, a spec), with:

| Column | What |
|---|---|
| Kind | Diataxis: `tutorial`, `how-to`, `reference`, `explanation`; and two kinds kept apart, `generated` (a `GENERATED` marker in its first lines: a view, the reference, FEATURES.md) and `dated-spec` (a spec of `docs/specs/`, or a file named by its date: a record of that day) |
| Last commit | the day of its last commit in its own repo; `edited` when it has uncommitted changes |
| Owner | who answers for it, when it declares one |
| Sections | its Doc nodes |
| Cites | the nodes its sections cite (the `documented_in` edges into them) |
| Cited by | the docs whose sections name its path |
| Stale | the sections to re-read; `exempt` for a generated doc or a dated spec |

A doc declares its kind and its owner in its first lines, as an HTML comment Markdown does not show:

```markdown
<!-- doc: kind=how-to owner=ops -->
# Rotating the release key
```

Without one, its kind comes from its path: a runbook, `install.md` or `release.md` is a how-to, a tutorial or
quickstart a tutorial, `docs/reference/` or `formats.md` a reference, anything else an explanation.

`brain sync` writes the catalogue to `notes/docs_graph.md` (beside the store's other views), with the docs to re-read
and the declared links; `brain check` says when it is stale.

## Declared links

A doc that depends on another without citing it (its steps repeat the other's, it explains what the other decides)
gets a hand edge in one of the store's edges files, from its section to the other's, with the reason:

```yaml
- {from: "doc:myrepo:docs/runbook.md::restore", to: "doc:myrepo:docs/backup.md::layout", type: depends_on,
   props: {reason: "the restore steps follow the backup layout"}}
```

Its ends are checked like any edge's (`brain check`); one that does not join two Doc sections, or has no
`props.reason`, is a warning.

## Staleness: `doc.stale`

A hand-written doc is stale when, after its last commit:

- a node one of its sections cites changed: the node's entry in the store's YAML differs from the entry as of the
  doc's last commit (whole-line comments and blank lines aside, a comment at the end of an entry's line counts; a node
  created since counts; a node moved to another file with the same text does not), or
- a doc it declares to depend on was committed, or has uncommitted changes.

A doc of the store's own repo is compared with the store at its own last commit, so a doc merged together with its
node's change (a merge commit included) is not stale. A doc of another repo of the project is read from that repo's
checkout on the machine (as the links graph reads it) and compared with the store's last commit made before its own;
without a checkout it has no last commit and is never stale.

Each stale section is named (section level). A doc with uncommitted changes is being edited and is never stale;
generated docs and dated specs are exempt (a spec is history: the reference is the present).

- `brain check` warns, one line per doc: `doc.stale: <path>: N section(s) to re-read (a cited node or a declared
  parent changed after its last commit; notes/docs_graph.md)`, the docs of the project's other repos included.
- The view is a function of the store's own repo: a doc of another repo is listed there with its kind, sections and
  citations, but its last commit and its staleness only in `brain check` (that repo's checkout moves on its own).
- `brain audit --diff` (the scout) adds an info line `doc.reread` for each doc the change does not touch whose
  sections cite a node the change edits, in a store of the changed repo: the docs to re-read before the PR merges.
  It never blocks. `brain impact` lists the docs a change of code reaches.

Re-reading a doc and committing it (even a one-line touch-up) clears its staleness.

## docgraph/v1

`brain docgraph emit [--out FILE]` writes the catalogue as a [docgraph/v1](docgraph.md) document: a `document` node
per Doc section (its file's kind, owner and last commit, `status: stale` when it is), the cited nodes of the types the
contract has (ADRs and DDRs as decisions, work items, milestones, tests, lessons as findings), `documented_in` edges,
the declared links as `depends_on` with `origin: declared`, and the findings of the checks it runs (`doc.stale`,
`cycle` among the declared links; the others listed as not run). It exits 1 on an error finding.
