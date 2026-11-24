section: Added

- Presets and personas beside a module registry (`brain.presets`, `wi-brain-sigma-personas`): a store that keeps
  `modules.yaml` may keep `personas.yaml` (a new format, `v: 1`, `schemas/personas.schema.json`), its presets, each a
  set of bricks, modules and distributions, with optional ones and whether it uses AI. `brain modules --check`
  validates the file (exit 1; `brain check` warns), and the new `brain modules --personas [--json]` runs two checks
  on each preset: its set closed under the map's hard dependencies (`open`, or `incomplete` while a module's
  dependencies are unclassified, never a silent pass), and a preset without AI pulling no AI module nor a
  distribution that ships one (`violated`; the map's `ships_in` says which distributions ship which modules). Exit 1
  when a preset is open or violated; `brain modules --check` and `brain check` warn of each fault (docs/modules.md,
  « Presets and personas »).
