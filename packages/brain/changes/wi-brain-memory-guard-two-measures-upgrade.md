section: Upgrade

1. **Check the usage guard's RAM floor** (`wi-brain-memory-guard-two-measures`). A new session or a workflow is now
   refused while the machine's available RAM is under `usage.guard.memory_available_gb` GB (default 4), whatever its
   committed memory. Nothing to do when the machine keeps more free; to lower the floor, set
   `"usage": {"guard": {"memory_available_gb": N}}` in config.json (0 turns it off). `brain usage guard` shows both
   measures and what each tool would get.
