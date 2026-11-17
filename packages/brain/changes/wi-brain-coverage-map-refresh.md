section: Added

- `brain coverage --from-ci [--cwd DIR]` reads the CI's coverage data of the HEAD of the checkout that holds `--cwd`
  (the `coverage-data` artifact of its successful push run on the default branch, workflow `ci.yml`, through `gh`;
  never a pull_request run, which measured another tree): the map's refresh after each merge, in a clean checkout at
  the merged commit, that one checkout giving the commit, the clean check and the sources; it says when the run is in
  progress or failed. `--from` now reads a data file against the checkout that holds `--cwd` (a worktree's paths are
  its own, no longer dropped as outside the registered checkout nor prefixed with a nested worktree's folder), and
  says so when none of its files is under that checkout; a relative `--cwd` is read from the top of the current
  folder's checkout for both; `--run`, `--from` and `--from-ci` exclude one another. `brain test --changed` also
  selects, on any Python change, the test modules that read the package's sources as text (a glob of `*.py`, `*.sh`
  or `*.ps1`, a walk or a listing of a folder, or a `# brain: scans-sources` line), which no coverage context links to
  the module they read (`wi-brain-coverage-map-refresh`).
