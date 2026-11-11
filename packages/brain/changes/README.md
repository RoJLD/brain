# Changelog fragments of the `brain` command

(`wi-brain-changelog-unreleased-collisions`; the script is `installer/changelog.py`.)

A PR does not edit `packages/brain/CHANGELOG.md`: it adds one file here, `<item-id>.md` (or a short slug), so that two
PRs never write the same lines and none is left CONFLICTING on GitHub once another merges.

```markdown
section: Fixes

- `brain x` no longer ... (`wi-brain-x`).
```

- The first line names the section: `Upgrade`, `Added`, `Fixes` or `Changes`.
- Then a blank line, then the entry as it will read in the CHANGELOG. For `Upgrade`, write the step (its bold title
  first); the version PR numbers the steps.
- Several entries of one PR in different sections: one file per section (`wi-brain-x-upgrade.md`, `wi-brain-x.md`).
- A section's fragments follow one another in file-name order: a list after a list continues it, anything else (a
  closing paragraph after the Upgrade steps) gets a blank line before it.

The version PR compiles them into `## X.Y.Z — YYYY-MM-DD — theme` and deletes them:
`python packages/brain/installer/changelog.py compile X.Y.Z --theme "..." --write` (docs/release.md, « 2. The
version PR »). `release-check` refuses, on every PR, a malformed fragment and a `## Unreleased` section in either
CHANGELOG, and on a version PR a fragment left uncompiled.
