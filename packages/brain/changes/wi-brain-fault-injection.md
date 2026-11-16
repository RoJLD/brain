section: Added

- A virtual clock and injected faults (`brain.faults`, `wi-brain-fault-injection`): `BRAIN_NOW` (a frozen point,
  `2030-01-31T22:00:00Z`, or a shift of the real clock, `+3d`) is the engine's « now » in the shared helpers
  (`brain.stateio`'s stamps and log months, `brain.net`'s breaker windows, `brain quiet`, the modules' `_now`
  helpers); `BRAIN_FAULT=<point>[@<glob>]:<kind>` injects `write:disk-full`, `write:killed` (exit 137 before the
  move), `read:corrupt` (the disk unchanged) and `net:timeout` or `net:refused`, so the command line and the suite
  play a failure end to end. A value the engine cannot read makes a command refuse to run (exit 2). `brain quiet`
  writes its state atomically and says a write it could not make (exit 1) instead of a traceback.
