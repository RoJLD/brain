section: Added

- The standards registry (`wi-brain-standards-registry`, [docs/standards.md](docs/standards.md)): standards as data,
  one row per standard (its domain, statement, the profiles it applies to, the stage it is required from, how it is
  enforced and by what check, the languages that check covers, how the Brain itself meets it, proposed or
  validated), in catalogs of a new format (`schemas/standards.schema.json`, `v: 1`): the engine's own under
  `src/brain/catalogs/`, and a brain's local ones that a project names. A project opts in with a new optional
  `projects.yaml` key, `standards: {profiles, stage, include, exclude, catalogs}`. `brain standards list|show|check`
  reads them (`check` exits 1 on a broken catalog, an id found twice or an unknown profile, stage or id, and lists
  the applicable standards whose check does not cover a repo's language); `brain check --all` checks every
  project's `standards:`, and `brain brief` lists the project's applicable standards as its invariants. A project
  without the key follows none: nothing is newly refused. A brain older than this one notes `standards:` as an
  unknown key (refused in CI's strict mode), so the key lands in a registry once its CI runs this engine.
