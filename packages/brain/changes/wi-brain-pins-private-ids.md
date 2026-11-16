section: Added

- Each decision pin has a public alias, which a public repo's PR body says in place of the private decision's id
  (`Keeps <alias>`, `Overrides <alias>: why`): its `alias` (`brain adr pin ID --alias NAME`), else `pin-` and 8 hex
  digits of the id's sha-256. `brain review check`, `brain merge-ready` and `brain impact --diff` give it; `brain
  check` warns on an alias of the wrong shape and on one alias given to two decisions; `brain adr pin` takes
  `--touches` only for a new pin (`wi-brain-pins-private-ids`).
