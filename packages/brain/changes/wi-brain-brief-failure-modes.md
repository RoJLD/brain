section: Added

- `brain brief` writes « Invariants and failure modes to test »: one line per surface kind the item touches (a store
  or a persisted format, a procedure step, an external system, a write in several steps, a command line, a heuristic,
  a guard, a counted set, a moved test, text into another format), each with what matched it and what to test, the
  public engine's line when a repo it touches is public, then the item's own `props.invariants`; `brain review prep
  --item ID` gives the review's agents the same section, and without `--item` the diff's (`brain.failuremodes`,
  `wi-brain-brief-failure-modes`).
