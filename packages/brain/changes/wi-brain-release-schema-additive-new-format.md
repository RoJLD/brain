section: Changes

- `release_check.py`: a format the last tag did not register (its own `SCHEMAS`) none of whose files exists there
  (a format this version adds, `new_formats`) is reported on its own line and is a patch's; a file new to a format
  that exists, or a format whose files are renamed, still moves it (`wi-brain-release-schema-additive`).
