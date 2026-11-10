# Changelog fragments of `research-graph`

(`wi-brain-changelog-unreleased-collisions`; the script is `packages/brain/installer/changelog.py`.)

A PR that changes `research-graph` (`src/research_graph`) adds one file here, `<item-id>.md`, instead of editing
`CHANGELOG.md`: its first line `section: Added`, `Fixes` or `Changes`, a blank line, then the entry. The version PR
compiles them (`python packages/brain/installer/changelog.py compile X.Y.Z --theme "..." --write`); with none, the
release's section says « No change ». The rules are those of `packages/brain/changes/README.md`.
