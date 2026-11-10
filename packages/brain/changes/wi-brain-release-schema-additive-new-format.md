section: Changes

- `release_check.py`: a registered format none of whose files exists at the last tag (a format this version adds,
  `new_formats`) is reported as grown and is a patch's; a file new to a format that exists still moves it
  (`wi-brain-release-schema-additive`).
