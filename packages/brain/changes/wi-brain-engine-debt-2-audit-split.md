section: Changes

- `brain.audit` is split by concern, its behaviour unchanged: the checks and their ruleset (`brain.audit_checks`),
  the measure of a project's repos (`brain.audit_measure`), the trend and the milestone (`brain.audit_trend`), the
  outputs (`brain.audit_render`); `brain.audit` keeps the backlog sync and the command, and every name it had
  (`brain.audit.measure`, `CHECKS`, `RULESET`, ...: `__all__`), so a plugin that imports them needs no change. A test
  that patched `brain.audit.PENDING`, `CALIBRATED` or `_repo_tokens` now patches the module that reads it
  (`brain.audit_checks`, `brain.audit_measure`).
