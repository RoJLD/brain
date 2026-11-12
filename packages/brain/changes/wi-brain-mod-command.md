section: Added

- `brain mod list | show | enable | disable | explain` (`wi-brain-mod-command`): the module face of `brain profile`
  on the same files. `config.json` `tier.components` and `profile.json` accept the module ids of the store's registry,
  expanded to their capabilities (a capability named directly wins). `tiers.yaml` capabilities gain `depends_on`
  (hard: pulled at enable, a needed one refused at disable unless `--cascade`) and `uses` (soft). `enable` and
  `disable` print the plan and the cost, and `--apply` writes this machine's `profile.json`. `explain` shows each
  layer (the preset, config.json, profile.json, the dependencies pulled, the scopes' capabilities as declared).
  `brain init` writes an empty `modules` key.
