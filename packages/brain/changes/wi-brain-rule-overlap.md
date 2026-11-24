section: Added

- `brain check`, in a brain's own root, warns when one of the brain's texts restates another: a rule, a procedure
  step or a memory note (a `## ` section, or a file without one) whose entity-neutral 8-word shingles (ids, dates,
  numbers and the brain's entity names dropped) are at least `overlap.warn` percent of the smaller unit's
  (`brain.overlap`, `docs/overlap.md`; the method of agency-agents' originality check, MIT, rewritten in Python). A
  warning, never an error. New `config.json` keys, all optional: `overlap.roots` (default the neutral source's rules
  and procedures and the memory notes), `overlap.exclude` (default `**/MEMORY.md`), `overlap.warn` (default 20) and
  `overlap.min_shingles` (default 10); an older engine notes and keeps them. `brain review prep` adds the pairs a PR's
  touched files take part in to the packet's notes when the procedure lens is called (`wi-brain-rule-overlap`).
