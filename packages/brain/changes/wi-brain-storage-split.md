section: Added

- `brain spool push`, run by hand: the sealed local spool of the stores that leave the machine (`$BRAIN_HOME/spool`,
  a new engine store, class sealed). It seals each changed store of its set (`spool.stores`, else the ledger, the
  usage and the session records) through `brain vault` after a secret scan, refuses a store whose class never leaves
  the machine, seals a store again when its recipients change, sends what waits to `spool.remote` when one is set (a
  folder), each copy checked by sha256, and keeps the last 3 snapshots per store. `brain spool status` and `verify`;
  `brain health spool` gives the age of the last push without an error. The `spool` block of config.json is optional
  and additive; nothing runs until a first push (`wi-brain-storage-split`).
