section: Added

- `brain <project> <subcommand> ...`: a project's command plugin, named under its `plugin` key in `projects.yaml`
  (reserved until now), runs its subcommands (`brain.plugins`). The value is an entry point of the group
  `brain.plugins` or `module:attr`; the plugin is a command module (`register` and `run`, as brain's own) or a
  callable `main(argv)`, so a project's own CLI plugs in unchanged and stays a shortcut of `brain <project>`.
  `brain --help` lists the plugged projects without importing them; a plugin that cannot load fails its own run only
  (exit 2); `brain check --all` reports a project named like one of brain's commands, whose plugin would never run.
  A registry without the key behaves as before (`wi-brain-command-plugins`).
