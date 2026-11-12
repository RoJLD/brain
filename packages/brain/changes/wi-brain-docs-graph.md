section: Added

- The documentation graph (`wi-brain-docs-graph`, [docs/docs-graph.md](docs/docs-graph.md)): for a store with the
  `Doc` type, a catalogue of every doc file (its Diataxis kind, `generated` and `dated-spec` apart, its last commit,
  its owner when the doc declares one in its first lines, the nodes it cites, the docs that cite it), declared
  `depends_on` links between doc sections with their `props.reason`, and `doc.stale` at section level: a hand-written
  doc whose cited node changed (its YAML entry) or whose declared parent was committed after its own last commit.
  `brain sync` writes the generated view `notes/docs_graph.md`; `brain check` warns on the docs to re-read and on a
  declared link without its reason; `brain audit --diff` adds an info line `doc.reread` for each doc a change does not
  touch that cites a node it edits; `brain docgraph emit` writes it as a docgraph/v1 document. A brain made before
  can add `notes/docs_graph.md merge=brain` to its `.gitattributes` and the view's `generated` side to
  `boundary.yaml`, as `brain init` now writes them; until then the view merges as plain text.
