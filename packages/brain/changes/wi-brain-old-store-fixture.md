section: Added

- The old-store fixture (`wi-brain-old-store-fixture`): `tests/fixtures/stores/<tag>/brain/` holds a brain as a
  released engine wrote it through its own commands (v0.2.4, before the Lesson type, and v0.3.1), and
  `tests/test_old_stores.py` runs this checkout's `brain check`, `sync`, `record check`, `item`, `items`, `lesson` and
  `retro` on each, strict. `installer/freeze_store.py vP` freezes the last tag's store, and the version PR's
  `release-check` refuses a version without it (docs/release.md, « The fixture freeze »). For a brain, one change:
  the scout and the Doc links leave a frozen store (`tests/fixtures/stores/**` in any test folder) out of the docs
  set and the shape signals, so a README under such a folder is no longer a Doc node after the next `brain sync`;
  nothing newly refused.
