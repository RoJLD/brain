section: Added

- Reading the documentation graphs of the projects a brain only reads (`wi-brain-docgraph-read`,
  [docs/docgraph.md](docs/docgraph.md), « Reading several documents »): `brain docgraph pin PROJECT --from CLONE
  --ref REF --file PATH` copies an `access: read` project's docgraph/v1 document from a local clone at a commit (`git
  show`, never a checkout), validated, to `docgraph/PROJECT.json` under the brain's root with the commit it was read
  at (`pinned`), committed by PR; the registry entry is unchanged. `brain docgraph join` reads the brain's own graph,
  the pinned copies and the documents the brain keeps for itself as one docgraph/v1 graph, ids namespaced by project
  (`item:example/25`; an edge may name another document's node by that id), and runs ten named checks again across
  it, the producers' own findings kept; exit 1 when a document is left out or an error is found. `brain check` in a
  brain's own root warns on a document under `docgraph/` the join leaves out, and `brain reference` gives each pinned
  project a page under `docs/reference/read/`.
