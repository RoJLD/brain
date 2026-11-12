section: Added

- `docgraph/v1`, the documentation graph's neutral contract (`wi-brain-docgraph-contract`,
  [docs/docgraph.md](docs/docgraph.md)): a public, versioned JSON format any program may emit for a project's
  documentation graph (decisions, documents and sections, milestones, criteria, items, changes, tests, threats,
  modules, owner decisions, findings and the needs of later phases), normalised statuses, edges named as the Brain
  names them (`constrains` with its compatibility included), a source on every node and derived edge, declared links
  with their reason and `confirmed`, and the findings of sixteen named checks with their meaning. Its schema is
  `schemas/docgraph.schema.json`, registered with the other formats, with an invented document of each side of the
  version in `tests/fixtures/formats/docgraph/v1/`; it evolves by the status contract's rule (optional keys added in
  v1, a new type, status or meaning is v2; `release-check` counts an optional key added to its schema as a patch, the
  owner's answer of 2026-11-12). Nothing in it assumes code: a `change` is any reviewed modification, and a producer
  with no code (a research or writing project) emits the same nodes. `brain docgraph validate FILE...` checks a
  document against it (exit 1 when invalid or written for a later version) and `brain docgraph checks` lists the
  named checks; neither needs a brain.
