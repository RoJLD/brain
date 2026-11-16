section: Fixes

- `release_check.py --store` and `brain wave check X.Y.Z` name the wave a version PR closes, and how when it ships
  under another number (`wave-s3 (1.0.2, closed as 1.1.0, a jump)`), and no longer pass a version that names no wave
  when the wave before it was reached by hand without `props.shipped_as`: whether it shipped as that version cannot be
  told, so the closure rule would pass unread; `brain item set <wave> props.shipped_as=X.Y.Z` records it
  (`wi-brain-release-check-shipped-wave`).
