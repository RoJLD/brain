section: Added

- Each format as a released engine wrote it (`wi-brain-format-fixture-freeze`): `installer/freeze_store.py` also
  freezes each registered format's file the tag's engine wrote, `tests/fixtures/formats/<format>/v<N>/<tag>.<ext>`
  (ar, config, ddr, event, packs, projects, sr, template; from v0.2.4 and v0.3.1), and `tests/test_formats_frozen.py`
  reads each one strict. `--only-formats` and `--reuse` freeze them alone from a kept freeze. The status document is
  never frozen (a machine's inventory). The engine's own tests only: nothing changes for a brain.
