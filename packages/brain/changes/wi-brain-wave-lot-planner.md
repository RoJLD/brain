section: Added

- `brain wave plan [X.Y.Z] [--at-once N] [--hot NAME]... [--json]`: a wave's lots at zero token (`brain.lots`). The
  open items whose predicted surface (`brain collisions`') shares a file go into one lot, run in the order of their
  `depends_on`; hot files (READMEs, CHANGELOGs, `formats.md`, `FEATURES.md`, `config.schema.json`, `changes/`) are
  counted apart. A lot that holds another's prerequisite comes a round earlier, the lots that unblock the most first,
  at most the sessions cap in force less the master's and the PRs verified at once (3) a round. It prints the
  predicted conflicts, the hot files shared, the items with no known surface and what the memory guard and the last
  quota forecast say now, and refuses nothing; `brain next` shows the current wave's first round
  (`wi-brain-wave-lot-planner`).
