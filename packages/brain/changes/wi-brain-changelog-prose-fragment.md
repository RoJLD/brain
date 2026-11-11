section: Fixes

- `changelog.py compile` puts a blank line before a fragment that is not a list when it follows another in the same
  section, so a closing Upgrade paragraph such as « Nothing to run for the rest » no longer joins the last numbered
  step; a list after a list still continues it (`wi-brain-changelog-prose-fragment`).
