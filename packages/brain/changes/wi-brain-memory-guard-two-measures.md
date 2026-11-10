section: Changes

- The usage guard's memory check reads two measures (`wi-brain-memory-guard-two-measures`): it refuses a new session
  or a workflow when committed memory reaches `usage.guard.memory` % (default now 97, was 90) or the available RAM
  falls under `usage.guard.memory_available_gb` GB (new, default 4). Its refusal, `brain usage guard` and
  `brain status` (a new `memory` row) show both measures and name the one that refuses. Committed memory alone (what
  Windows promised, RAM plus page file) refused every start at 93-96 % while a third of the RAM was free. The
  governor's settings cache now keys on the defaults, so an upgrade never keeps the old cap.
