section: Added

- `brain wave placements [ID]... [--all] [--json]`: where each open item may go among the waves, at zero token
  (`brain.placement`, `docs/placements.md`). An item's new `props.place` (format v1: `;` clauses such as `wave s11`,
  `wave s11 or s12`, `earliest`, `latest`, `before 1.0`, `after 1.0`, `after wi-a`, `with wi-b`, `own-lot`, `round N`,
  `proposed`, `unplaced`, `out owner|later|trigger`) is authoritative; else the placement words of its free text
  (`props.wave_planned`, `planned_wave`, `wave_fit`, `wave`, `after_1_0`, the `decided_*` answers, `track`) are read,
  never guessed. Each item is resolved to wave places and a status (composed, pinned, choice, constrained, free, out,
  unparsed, none), with its `props.place` form; the questions it leaves (a choice, two waves in one text, sources that
  disagree, bounds that contradict, a wave reached or dropped, a wave or an item named that is not there) are listed.
  Its `--json` keys are a public contract (`format` 1, keys only added). `brain check` warns on a malformed
  `props.place` (`wi-brain-placement-grammar`).
