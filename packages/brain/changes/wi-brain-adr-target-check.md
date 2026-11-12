section: Added

- Checking a decision against the target before it is accepted (`wi-brain-adr-target-check`,
  [docs/adr-target.md](docs/adr-target.md)): `brain adr new --scope S --target ID=COMPAT[:note] --leaves-open T`
  writes a one-way door's Scope and Target compatibility (each future need it touches, compatible, an extension point
  or to review, and what it leaves open; one without the other is written TODO). `brain adr target [--needs] [--json]`
  computes the register of future needs from the graph (the planned features, the pending milestones with a trigger,
  the open items of later waves and of the pending eras) and runs three advisory checks on the one-way doors (an ADR
  with either field, written by the command or by hand as a label or a sentence): `decision.target-compat-missing`,
  `decision.review-trigger-missing` and `decision.target-unreferenced` (an open need of a module the ADR decides that
  it does not cite). `brain docgraph emit` adds the register, the one-way decisions and their `constrains` edges to the
  brain's documentation graph, and `brain docgraph join` runs `decision.target-unreferenced` across the joined graph.
  Two-way doors are never checked.
