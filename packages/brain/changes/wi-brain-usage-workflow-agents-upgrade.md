section: Upgrade

1. **Check the usage guard's parallel-sessions cap** (`wi-brain-usage-workflow-agents`). The cap that the week's room
   pays for now uses the session-hour cost `brain usage quota` measured, whenever it is above
   `usage.guard.session_hour_usd`. The measured cost includes the subagents and the workflow agents. On a machine
   whose sessions run workflows, the cap can be lower than before, and a new session can be refused where it used to
   pass. Run `brain usage quota` to see the `session-h` line, then `brain usage guard` to see the cap. The owner's
   override is unchanged: `brain usage allow` in their own terminal.
