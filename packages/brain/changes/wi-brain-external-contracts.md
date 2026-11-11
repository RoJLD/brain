section: Added

- External formats under contract (`wi-brain-external-contracts`, docs/formats.md « External formats »): the capture
  hook counts the keys of Claude Code's hook payloads it does not know or misses, and the Stop hook the transcript
  records of an unknown type or without a key it reads, in `ledger/contracts.json`; a first sighting goes to
  `errors.log` and the next SessionStart health names it once, and nothing is refused. The status document that
  `brain doctor --json` prints is published as `schemas/status.schema.json`, a new format (`status`) with its fixtures
  in `tests/fixtures/formats/status/v1/`: any contract id of config.json `inventory.schema`'s pattern, default
  `brain.status/v1`. Real-shaped fixtures of each captured hook payload and of a transcript are in
  `tests/fixtures/claude/`.
