section: Changes

- Waves get ids without a version (wi-brain-wave-ids-decoupled, the owner's WAVES-3 to WAVES-5): `brain wave add`
  creates `wave-sN` (N its place, `props.seq`) and its release is a computed label, the next patch after the wave
  before it, unless pinned (`props.release`); `brain wave close X.Y.Z` writes `props.shipped_as` and, when the release
  jumped to the next minor or major, closes the current wave by that version, so the later waves' releases follow
  without an edit; `brain wave check`, `release_check.py --store` and `brain wave close` resolve a wave by its id, a
  former id (`props.renamed_from`), its label or what it shipped as. New `brain wave rename WAVE [NEW] [--write]`
  renames a legacy `wave-X.Y.Z` once. Legacy waves keep their ids and read as before. `brain wave add X.Y.Z` now
  refuses a release other than the computed one (a store's first wave names it).
