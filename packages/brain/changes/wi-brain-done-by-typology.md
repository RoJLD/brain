section: Added

- The definition of done by typology (`wi-brain-done-by-typology`, spec-brain-typology-packs E2): a generic sentence
  for every item (documented, verified, linked, integrated, recorded), then the clauses of its typologies, from the
  typology catalog (the software pack's: a PR, a test, the docs in the same PR, the scout, the worktree; research's:
  pre-registered, verdict, reproducible). An item's typologies are its `props.typology`, else its project's
  `lifecycle.typologies`, a new `projects.yaml` key (LC-1; its other keys kept as declared). `brain item clauses ID`
  prints them; `brain item close` takes `--evidence TEXT` beside `--pr`, and requires `--pr` only for an item that
  takes a PR clause, or whose project declares no typology, as before.
