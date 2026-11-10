section: Changes

- The engine's CHANGELOGs are written from fragments (`wi-brain-changelog-unreleased-collisions`, the owner's choice
  of 2026-11-10): a PR adds `packages/brain/changes/<item>.md` (or `changes/<item>.md` for research-graph), a first
  line `section: Upgrade|Added|Fixes|Changes` then its entry, and never edits a CHANGELOG, so parallel PRs no longer
  collide in one `## Unreleased`. The version PR compiles them with `installer/changelog.py compile X.Y.Z --theme T
  --write`; `release-check` refuses a malformed fragment and a `## Unreleased` section on every PR, and a fragment
  left uncompiled on a version PR. The CHANGELOGs are `merge=brain` in `.gitattributes`, a net for a merge back from
  `release/X.Y` (`wi-brain-engine-changelog-driver`); a clone gets the driver with `brain merge-driver install
  --apply`.
