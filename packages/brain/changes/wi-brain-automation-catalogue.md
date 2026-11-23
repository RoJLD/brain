section: Added

- `brain automation list [--json]`: the automation catalogue (`brain.gestures.CATALOGUE`, docs/automation.md), every
  recurring owner gesture, the ones a session runs too (the engine clone's pull, a session's archive, Remote Control
  at a hand-over, the merge go, a workflow's launch) and every owner-only command: its stable id (the key
  `config.json`'s coming `automation` section will set a level by), its level today and its source, its ceiling
  (manual, ask or auto: the highest level the engine allows), where it runs (a session, the owner's terminal, their
  elevated terminal, the harness), its conditions and its floor category (AUTO-1: the never-grantable categories, the
  elevated terminal, the rules' text and raising a level, locked at manual). `brain.gestures.effective` reads a level
  above its ceiling, unknown or unreadable, and any level of a floor gesture, as manual. Read only, zero token; no
  guard reads the catalogue yet (`wi-brain-automation-catalogue`).
