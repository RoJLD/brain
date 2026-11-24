section: Added

- `brain milestone path [--check] [--json] [--history] [--width N]` and the Milestones tab's Path view (`v`, after
  Trajectories; `brain tui --once --tab milestones --view path`): the order of the milestones (UX-12). An arc A → B is
  derived when an item of B still waits on an item of A (both open; `--history` counts the done pairs too), weighted
  by its pairs of items; a declared `depends_on` between two milestones wins over a derived arc the other way. The
  ranks run left to right with the milestones of a rank in parallel, each with its items done out of its live items
  and its p50; a mutual wait is a knot `⟦a ⇄ b⟧`, and `--check` lists each one with its pairs each way and how to
  settle it (exit 1 while one is left); `◆` marks the longest chain of p50 work. Under 120 columns the path is a tree.
  `cockpit.milestone_layers` gives the data to the view, the command and the later PERT and HTML views; `--json` is a
  public contract (`v` 1) (`wi-brain-milestone-order`).
