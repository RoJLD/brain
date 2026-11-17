section: Changes

- `brain.audit` is split by concern, its behaviour unchanged: the checks and their ruleset (`brain.audit_checks`),
  the measure of a project's repos (`brain.audit_measure`), the trend and the milestone (`brain.audit_trend`), the
  outputs (`brain.audit_render`); `brain.audit` keeps the backlog sync and the command, and every public name it had
  (`brain.audit.measure`, `CHECKS`, `RULESET`, ...: `__all__`, the same objects), so a plugin that imports them needs
  no change. A private helper (`_moved`, `_repo_tokens`, ...) is now its module's, and a patch must name the module
  that reads the name: `brain.audit_checks.PENDING` and `CALIBRATED`, `brain.audit_measure._repo_tokens`, and
  `brain.audit_measure.measure` for the trend's weeks (a patch of `brain.audit.measure` reaches `brain audit`'s own
  measure only) (`wi-brain-engine-debt`, batch 2).
