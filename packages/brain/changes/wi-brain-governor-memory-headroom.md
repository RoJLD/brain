section: Added

- The governor's memory cap in GB of commit left (`wi-brain-governor-memory-headroom`): config.json
  `usage.guard.memory_free_gb` (default 0: the percent, as before) refuses a new session or workflow under that
  many GB of commit left (Windows: the commit limit minus the commit charge; elsewhere MemAvailable plus SwapFree),
  the percent then not read: a fixed page file keeps it at 91-94 % with 25 GB of RAM free. `brain usage guard`,
  `brain status` and `brain lots` show the commit left when it is set (docs/guards.md, « The usage governor »).
