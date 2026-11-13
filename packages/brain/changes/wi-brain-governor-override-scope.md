section: Changes

- `brain usage allow` lifts checks, not the whole usage governor (`wi-brain-governor-override-scope`): by default the
  memory and session caps (`memory`, `sessions`, `brainstorms`), a quota threshold only when named (`--check
  critical`, which lifts `warn` too, `--check warn`; repeatable), a stale quota reading never (reading it again is one
  `get_usage` call). A lifted check lets the next one decide, each refusal names the allow that lifts it (or says none
  does), and each allow and its end (ended, replaced or expired) are lines of the guards ledger, with each call it lets
  through. `BRAIN_GUARD_ALLOW=usage:CHECK` now lifts that check only (`usage` and `all` still lift every check). An
  `allow.json` written by 0.5.0 lifts what it lifted then until it ends.
