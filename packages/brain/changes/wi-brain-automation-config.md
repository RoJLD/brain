section: Added

- config.json's `automation` section, version 1 (`{"v": 1, "levels": {gesture id: manual, ask or auto}}`;
  `brain.automation`, docs/automation.md): a gesture's level is the engine's default (today's behaviour: a new engine
  never raises one), then the section, then `<BRAIN_HOME>/automation.json`, a machine file of the same shape that may
  only lower a level. A config.json that `$BRAIN_CONFIG` names never raises a level above the one found without it
  (the engine's default when none is found). Fail closed: a level above its ceiling, unknown or unreadable, any floor
  gesture's, and a section or file this engine cannot read, read `manual`; an id the catalogue does not hold is
  ignored with a note. `brain automation explain [GESTURE] [--json]` says, layer by layer, where each level comes
  from, and `brain automation list` shows each level's source. `brain config --check` and `brain check` refuse a
  floor gesture set above `manual`; an unknown id, an unknown level or one above its ceiling is a note (an error in
  strict mode, CI). No guard reads a level yet (`wi-brain-automation-config`).
