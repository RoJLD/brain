section: Fixes

- `docs_graph.md` no longer goes stale on main after every PR that touches a doc: its Last commit column shows today
  for a doc with uncommitted changes (a new one included), the day its commit will carry, instead of `edited`, which
  became a date once the PR merged and asked for one more views PR (`wi-brain-docsgraph-edited-loop`).
