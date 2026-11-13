section: Changes

- Waves, after the review of their ids (wi-brain-wave-ids-decoupled): `brain wave close` reads `--carry-to` against
  the plan once the wave is closed (after a jump, `--carry-to X.Y.Z+1` is the wave that follows, not a second one), a
  created wave goes last and pins its release only when it is not the computed one; a dropped wave holds no release
  (its id still resolves); a later wave labelled as the current wave's jump is said ambiguous. `brain check` refuses a
  pending pinned release a jump left behind, a `props.seq` of 0 and a place two waves hold; the closure refuses a
  version PR that leaves a pending wave below it. `brain wave rename` rewrites only YAML values, the generated files
  too, makes a default title « Wave sN » and refuses a NEW that is another wave's former id. `brain review stamp`
  records the wave's id (`wave_id`, additive) and `brain review score` counts it in its wave's release now.
  `brain wave import` lives in `brain.waveimport`.
