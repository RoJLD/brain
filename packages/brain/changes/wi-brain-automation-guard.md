section: Changed

- The automation levels enforced (`wi-brain-automation-guard`, spec-brain-automation-levels S3; docs/automation.md
  « Enforcement »): the guard hook reads `session-archive`'s level on `archive_session` (and on the
  `set_remote_control` off before an archive) and `handover-remote-control`'s on a hand-over's Remote Control, inside
  their conditions: `manual` refused (an archive outside them too, and when the ledger cannot log the refusal), `ask`
  (the engine's default) the guard's own `permissionDecision: ask`, the card, logged `asked`, whatever the tool's
  native rule (the other gesture's allow on `set_remote_control`, or a level lowered since the last render: a lowering
  holds at once; an owner's allow rule no longer lifts the card, their level `auto` does), `auto` allowed with no card
  (`permissionDecision: allow`). `ask` reads `manual` in a permission mode
  where an ask shows no card (`bypassPermissions`, `dontAsk`, an unknown mode or none given: refused). The guards
  ledger's rows carry the `level` they read. `brain permissions render --level user` (and `install.ps1 -Apply`) writes
  each of the two tools at the highest level of its gestures as a native rule (auto allow, ask ask, manual deny; an
  allow no guard sees withheld) and takes the tool's other verdicts out, so that an owner's allow rule for
  `archive_session` becomes the ask rule of the default level at the next install; `--json` adds `automation`. In an
  agent's session `brain refresh` and `brain release apply` fast-forward the engine clone at `engine-clone-pull`'s
  `auto` only, and say `not pulled` with the command below it. `brain automation explain` prints each gesture's
  `enforced:` line.
