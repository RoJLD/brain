section: Added

- An edge may name another store's node: `--foreign-store LABEL=PATH` (repeatable) gives the stores whose ids the
  edges may name, and `load_store(..., foreign=...)` takes them in Python (`loader.read_foreign`). Such an edge loads
  when one end is the store's own; the other store's node is shown by its id and its label in the board, the roadmap,
  `items`, `item`, `decisions` and `impact` (`wi-x (parent:graph)`), counted in a milestone's progress and as a
  blocker, never listed among the store's own nodes; the board lists an item whose only milestones are other stores'
  under « Part of another store's milestone ». Without the option nothing changes: an edge to an id the store does not
  hold is refused as before (`wi-brain-cross-store-edges`).
