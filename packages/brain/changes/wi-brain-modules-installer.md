section: Added

- `brain init`'s three screens (`wi-brain-modules-installer`, `brain.firstrun`), offline and with no telemetry: who
  you are (`--preset`: a preset of the brain's catalogue, Lite, Default or Recommended, or a persona of a private
  catalogue/v1 file, `--catalogue FILE`, on its base preset), your machine (the probe's facts and, per module, whether
  it runs here, its requirements and its RAM, VRAM and disk against the machine, and whether its `recommend_when`
  holds; an unknown fact is said, never assumed), adjust (`--with`, `--without`: each module's box, its cost, its
  hard dependencies pulled, what must be downloaded; a module the machine does not hold, a core or auto one, a
  planned one or one a module on needs is refused). `--interactive` (`-i`) asks the screens in a terminal and ends
  on the same choice as one command. The choice is brain commands, shown in the plan and, with `--apply`, run in
  order after the files and logged in `<BRAIN_HOME>/ledger/setup-<month>.jsonl`: `brain profile set BASE --apply`,
  then `brain mod disable ID --apply` for each module of the base left out (those that need another first), then
  `brain mod enable ID --apply` for each one added; a second apply changes nothing. A distribution to download (a
  pip extra) is named, never fetched. `--tier` now defaults to the preset's base (default for Recommended, frozen
  for the machine by brain profile set). Without these flags `brain init` is as before, and its plan names them.
