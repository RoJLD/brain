section: Fixes

- `release_check.py --store` and `brain wave check X.Y.Z` name the wave a version PR closes, and how when it ships
  under another number (`wave-s3 (1.0.2, closed as 1.1.0, a jump)`), and find it when a wave was reached without
  `props.shipped_as` (by hand, or by an engine up to 0.5.0): the last tag tells it (`release_check.py` knows it,
  `brain wave check X.Y.Z --tag vP` from the brain): the wave labelled the tag's release shipped as itself, the one
  reached after it ships as this version and is the one checked. When the tag does not tell and that wave could have
  shipped as this version (the next minor or major after what it counts from), the version PR is refused instead of
  passing unread or checking the next wave as a jump; `brain item set <wave> props.shipped_as=X.Y.Z` records it
  (`wi-brain-release-check-shipped-wave`).
