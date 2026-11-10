section: Added

- Edges between the stores of one registry (`brain.crossstore`): an edge may name a node another registered store
  holds. brain gives research_graph the stores that hold the ids a store's edges name (`--foreign-store`, on every
  run and in-process load: sync, check, the views, the pending questions, `brain impact`), so the store loads and its
  board and roadmap show the other store's node by its id and store (`wi-x (parent:notes/graph)`); `brain item link`
  and `brain item add` accept another store's id as one end. `brain check --all` counts the edges between stores and
  refuses one whose end is in no store of the registry on this machine, as the store's own check already did; without
  `--all` a brain's own root warns of it. A store whose edges name only its own ids runs as before
  (`wi-brain-cross-store-edges`).
