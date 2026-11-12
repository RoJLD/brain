section: Changes

- `brain perf --usage` lists apart, with how each is reached, the commands that never run from the CLI by design: a
  command module's `RUNS_VIA` declares a subcommand wired (a hook, another command or a schedule runs its code:
  `brain capture`, `brain decision announce` and `view`, `brain docs check`, `brain memory status` and `sync`) or run
  on demand (the vault's, the spool's and the identity's owner gestures, `brain down`, `brain standards show`, `brain
  docs render`); they are no longer gaps, nor make their feature unused. The close-item procedure's step 2b now runs
  `brain cost review <id> --record` after the retro (`wi-brain-adoption-gaps`).
