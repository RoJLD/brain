section: Changes

- `release_check.py` reads config.json's schema structurally (`wi-brain-release-schema-additive`): optional keys
  added to `config.schema.json` (none of them `required`) and prose changes no longer make a format move, so a patch
  may hold them; it reports them as grown. Any other change of it, and any change of a record schema (ar, ddr, sr,
  event), still makes the release a minor one (docs/release.md, « The version policy »).
