section: Added

- `brain check --public --refresh`: `brain check --public --history` in every local checkout of a public repo (the
  registry's repos whose remote is in `config.json` `public.repos`), by the running engine; a HEAD whose stamp is
  still valid is left (`same`), a checkout with tracked changes not committed is skipped and named, one with findings
  is named and not stamped. `brain update` runs it with the engine it just installed, and the installer's `-Apply`
  does too (its `stamps` step), so the push guard no longer refuses every push after an upgrade until the owner
  re-checks each checkout by hand; a finding or an older command is said, never an install failure
  (`wi-brain-public-stamp-refresh`).
