section: Added

- A project's own formats (`wi-brain-project-formats`, spec-brain-data-compat § 3, the owner's PF-1 answer « Opt-in
  run »): `projects.yaml` `formats:` registers each persisted format of a project (id, glob, repo, class, version,
  schema, fixtures, a `check:` command in any language that exits 0 or 1, its timeout) and `migrations:` the glob
  check of its database migrations (`when`, `add`, `repo`). `brain check` judges the declarations always (the shapes,
  then, where the checkout is here, a glob that matches, a schema and a fixtures folder that exist); the commands run
  only by `brain formats check` (or `brain check --formats`): with no shell, bounded (default 120 s, `--timeout`), a
  pass or a fail cached in `$BRAIN_HOME/formats/<project>.json` (a new store, sealed, derived) by the hashes of the
  command and of the files it judges, `--fresh` to rerun. `brain formats list` prints them. The scout (`brain audit
  --diff`) finds a `when` file changed with no file added for an `add` glob: a NEW `format.migration` finding, or a
  `Justified: <path>: <reason>` line. An older engine notes the two keys as a newer brain's and keeps them (in CI:
  refused): a registry declares them once every machine runs this release.
