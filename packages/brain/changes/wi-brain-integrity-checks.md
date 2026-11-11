section: Added

- Integrity of the engine's truth-local state files, opt-in (config.json `integrity.sidecars: true`, or
  `BRAIN_STATE_INTEGRITY=1`; off by default): each save through `brain.stateio` writes a sha256 sidecar beside the
  file (`<name>.sha256`: the hash, size and mtime) and each load checks it. A file whose size and mtime match but whose
  hash does not (bit rot) is set aside with a note (the copy kept, never saved over); one another writer changed since
  (an older engine) loads and gets a fresh sidecar; a missing sidecar loads as before (`wi-brain-integrity-checks`).
