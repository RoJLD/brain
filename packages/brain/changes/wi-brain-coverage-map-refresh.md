section: Added

- `brain coverage --from-ci [--cwd DIR]` reads the CI's coverage data of this checkout's HEAD (its successful run's
  `coverage-data` artifact, through `gh`): the map's refresh after each merge, in a clean checkout at the merged
  commit; `--from` now reads a data file against the checkout that holds `--cwd` (a worktree's paths are its own, no
  longer dropped as outside the registered checkout); `brain test --changed` also selects, on any Python change, the
  test modules that read the package's sources as text (a glob of `*.py`, an `os.walk`, or a `# brain: scans-sources`
  line), which no coverage context links to the module they read (`wi-brain-coverage-map-refresh`).
