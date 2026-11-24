section: Added

- `brain adr revisit [--all] [--today D] [--json]`: the ADRs in force whose « Revisit if » is already met or lapsed,
  read from their prose at zero token (`docs/revisit.md`): a node they name now done, reached, have, retired or
  answered (dropped: lapsed), a wave closed, a day or a span (« after a month ») past, a key of `config.json` changed
  in git since the ADR's day; each with its evidence. A flagged ADR that a later ADR names by its id is reviewed and
  left out (`--all` shows it). No change to the decision log. Its `--json` keys are a public contract (`v` 1, keys
  only added): `v, today, logs, adrs, with_revisit, flagged, reviewed, counts`. `brain resume` gains a section with
  the first flagged ADRs, and `brain digest` one with the triggers met in its window (`--json`: the new key
  `revisit`) (`wi-brain-adr-revisit-report`).
