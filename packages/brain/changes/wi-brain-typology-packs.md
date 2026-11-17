section: Added

- Typology packs (`wi-brain-typology-packs`, spec-brain-typology-packs E3, TYPO-1, TYPO-4): a pack of
  `source/packs.yaml` names its `typologies` and bundles what a kind of project adds to the core (`layers`,
  `standards`, `stages`, `done`, `doors`, `roles`, `guards`, `registry`), each part's shape checked by `brain check`
  and an id this engine does not know a note in read mode; the engine ships the `software` and `research` packs
  (`typology_packs.yaml`), taken by a brain with `from: engine` (its own keys laid over the engine's); the clauses of
  done moved from the catalog into these packs (an item's clauses unchanged); `brain typologies packs` lists them and
  `brain typologies propose PROJECT [--apply]` plans the packs a project's `lifecycle.typologies` meet (the layers its
  store lacks, the standards it does not opt in to) and writes only the packs.yaml steps, nothing turned on silently
  ([docs/typologies.md](docs/typologies.md#typology-packs)).
