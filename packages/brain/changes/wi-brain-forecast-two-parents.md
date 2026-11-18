section: Changes

- `brain forecast` keeps both parents of an item that is part of a wave and of a thematic milestone: each item row of
  `--json` and `latest.json` carries `milestone` (its thematic milestone: the first not of kind wave, an era included),
  `wave` (the one it is in now: the wave its `props.carried_to` names once the planned one closed, else its own) and
  `parents` (every milestone it is part of, and that wave), additive keys of format 1; before, the last `part_of` edge
  won.
  « (no milestone) » now counts the open items with no thematic milestone, those in a wave alone included, and the
  slip a day of waiting costs (`brain queue`, `brain detail`) reads every milestone of the item, the tightest first
  (`wi-brain-forecast-two-parents`).
