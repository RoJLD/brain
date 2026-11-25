section: Added

- `brain wave propose [--waves N] [--from WAVE] [--items N] [--points N] [--at-once N] [--no-merged] [--against FILE]
  [--all] [--json]`: the wave composer, at zero token (`brain.propose`, `docs/propose.md`). It drafts the N waves after
  the last pending one from the open items' rank, `depends_on`, placements (`brain wave placements`: a pin, a choice,
  earliest, latest, `after` an item, `with` one, `own-lot`), sizes in points and a capacity (given, else what the last
  reached waves closed), the items merged but not closed counted done; each wave's items, standing batches, lots and
  rounds (`brain wave plan`'s cutter, six sessions at most), doors and release (a pending wave already composed keeps
  the plan's; a standing item composed there stays its batch), what waits on the owner, a pin's or a choice's
  prerequisites placed before it (due by the wave before, ahead of the overdue items); then the eras' due items, a
  `with` pair split and a choice missed asked, the items left out with their reason, the questions, the checks and the
  risks; `--against` an earlier
  `--json` says what moved. Its `--json` keys are a public contract (`format` 1, keys only added). It writes nothing
  (`wi-brain-wave-propose`).
