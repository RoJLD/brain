# The old formats' fixtures

One folder per format of `docs/formats.md`, one subfolder per version: `<format>/v<N>/older.*`, a file as the
previous release wrote it, and `newer.*`, the same version with a newer release's optional fields. The tests read
them (`tests/conftest.py`, `old_formats`): the reader of today reads both, and keeps what it does not know. Invented
data only: no real name, host, path or key.
