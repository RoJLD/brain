section: Added

- `brain project add NAME (--read | --existing DIR [--store PATH] | --template T --dir DIR) [--parent NODE] [--floor
  CLASS] [--title TEXT] [--apply]` (`wi-brain-project-add`): a project registered in the brain's `projects.yaml` by a
  command instead of a hand edit, a plan then `--apply`. `--read` writes a read-only entry (title, `access: read`,
  parent, classes), `--existing` the root of a folder that holds a graph store (relative to the registry's main
  checkout, checked to read back from a worktree, absolute when no relative path does), `--template` runs `brain init
  DIR --template T --name NAME` as a logged step and then registers it (refused on a machine without its pointer).
  `--parent` places it in the scope tree, `--floor` gives it a class floor, and the plan says what `public.deny.repos`
  gains when `public.deny_from_tree` is on. The registry as it would be is checked first (an error `brain check`
  would add refuses the write; one already there is left to `brain check`); the entry is appended with the file's
  comments, order and line endings kept, and the write is logged in `<BRAIN_HOME>/ledger/setup-<month>.jsonl`. The
  registry acted on is the one at `--root`, else `$BRAIN_PROJECTS`, else the nearest above the current folder, read
  with its own config.json and scopes.yaml; never the pointer's brain from another folder.
