section: Changes

- The locked floor watches only the variables that lift or redirect a guard (`wi-brain-floor-watched-vars`; under
  config.json `floor.refuse` or `floor.only`, both off by default): the `BRAIN_*` names stay watched as a class, but
  `BRAIN_STRICT` and the hints' switches pass, `BRAIN_NOW` and `BRAIN_FAULT` pass while the guard's home is the
  default one (the engine honours them on a scratch home only), and `BRAIN_CONFIG` and `BRAIN_PROJECTS` pass as one
  literal absolute path inside a worktree of the repository that holds config.json (`git worktree list`), in bash,
  `export`, `env` and PowerShell's `$env:` forms. `BRAIN_CONFIG` never lowers the floor the guard holds: the
  config.json found without it holds its floor too (`brain.config.anchored`), in Python and in `guard.sh`. The
  checkout that holds config.json pulls its upstream (`git pull`, `git pull --ff-only origin main`), judged by what
  the pull brings: main or master of a remote that is no local path, read when the pull is judged; a `git remote`
  that writes is refused in every worktree of that repository. On Windows the watched names are read in any case
  (`brain_home=`), `HOME` and `PATH` where the shell exports them, and `NAME[0]=` is an assignment; `guard.sh`'s
  pre-filter now starts Python for every shape of a watched assignment, which it let through without one (`BRAIN_HOME=x claude`)
  (docs/guards.md, « The environment »).
