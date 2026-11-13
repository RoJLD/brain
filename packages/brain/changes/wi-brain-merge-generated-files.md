section: Changes

- The merge driver resolves two more things a wave's integration resolved by hand (`wi-brain-merge-generated-files`).
  A node's status both sides moved merges by its order (done over doing over todo, reached over pending), the later
  side's value kept for each prop both sides changed: a branch's « doing » merged with the close on the default
  branch keeps the close, its PR and its notes; statuses with no order between them (doing and blocked, done and
  dropped) and any other key changed both ways stay a conflict. `brain reference`'s pages (`docs/reference/**/*.md`)
  are views once `.gitattributes` names them: one side kept, the path marked for `brain refresh`. `brain merge-driver
  install` now lists the lines a repo's `.gitattributes` lacks (`--json`: `missing`), the reference's where the repo
  holds `docs/reference/`; without the line git merges those pages as text, as before.
