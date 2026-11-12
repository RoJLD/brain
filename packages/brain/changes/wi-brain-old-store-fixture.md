section: Added

- The old-store fixture (`wi-brain-old-store-fixture`): `tests/fixtures/stores/<tag>/brain/` holds a brain as a
  released engine wrote it through its own commands (v0.2.4, before the Lesson type, and v0.3.1), and
  `tests/test_old_stores.py` runs this checkout's `brain check`, `sync`, `record check`, `item`, `items`, `lesson` and
  `retro` on each, strict. `installer/freeze_store.py vP` freezes the last tag's store, and the version PR's
  `release-check` refuses a version without it (docs/release.md, « The fixture freeze »). The engine's own release
  process only: nothing changes for a brain.
