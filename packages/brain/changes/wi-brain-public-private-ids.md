section: Added

- **The personal graph's ids refused in a public repo** (`wi-brain-public-private-ids`, brain.privateids): `brain check
  --public` and the public commit guard gain the `graph` check: an ADR's or a DDR's id of any store of the registry,
  any other id (`wi-`, `adr-`, `feat-`, `ddr-`, `spec-`, `les-`) of a project that is not the public repo's own, and an
  ADR's title (its first 8 words, whatever the case and punctuation). An invented id passes, as does a file under
  `public.allow`. The engine's own docstrings, a schema and a test no longer quote such ids or titles.
