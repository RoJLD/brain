section: Added

- `brain audit` checks the feature coverage, at zero token (check `feature.coverage`, `brain.feature_coverage`,
  ruleset 6): in a package whose `commands/` lists its own modules (a command registry), each command module (not the
  `_` helpers) and each module beside its `cli.py` must be named by a feature, by an active `implemented_by` CodeRef
  of its file or by a title that says it (`brain quiet`, `brain.stateio`). The full audit lists the ones no feature
  names as info, never counted, in a section per repo (`feature coverage: N of M ...`, the JSON key
  `feature_coverage`, a section of `notes/audit.md`). The scout (`brain audit --diff`) makes one the change adds a NEW
  line and one already there that it touches a DEFER line to the repo's debt item; nothing that passed is newly
  refused. `config.json` `audit.feature_coverage_strict` (a boolean, default false) is the owner's opt-in: true, the
  touched one is a LEFT line to fix in the PR (`wi-brain-audit-feature-coverage`).
