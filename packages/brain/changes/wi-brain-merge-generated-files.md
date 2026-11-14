section: Changes

- The merge driver resolves two more things a wave's integration resolved by hand (`wi-brain-merge-generated-files`).
  A node's status both sides moved merges by its order (todo, then doing or blocked, then done; pending, then
  reached), and for each prop both sides changed the later side's value is kept whole: a branch's « doing » merged
  with the close on the default branch keeps the close, its PR and its notes. Statuses of one rank (doing and
  blocked) or of no common order (done and dropped), a prop the later side deleted while the other changed it, and
  any other key changed both ways stay a conflict. `brain reference`'s pages (`docs/reference/**/*.md`) are views
  once `.gitattributes` names them: one side kept and the path marked, then rendered again (`brain refresh` for a
  brain's own render, `brain reference --write` for a public one). `brain merge-driver install` now lists the lines a
  repo's `.gitattributes` lacks (`--json`: `missing`): a brain's views where the repo holds `notes/graph`, the
  reference's where it holds `docs/reference/`; without the line git merges those pages as text, as before.
