section: Added

- `brain release tag vX.Y.Z`: the signed release tag in one owner gesture, from the engine checkout: its plan, one y
  (`--yes`; `--json` prints the plan), then the runbook's lines in order, stopping at the first that fails and saying
  which: `git switch main` (`--branch release/X.Y`; refused while a tracked file has changes), `git pull --ff-only`,
  the tag not on the remote yet, HEAD the version PR's merge commit (its message, both `__version__` moved by it,
  the CHANGELOG heading whose theme makes the tag message), `brain check --public --history` then `--private-text`,
  `git tag -s` (the owner's passphrase), the tag verified against the planning brain's allowed signers, the push of
  the verified tag object; a rerun resumes. An owner gesture (`brain.gestures`, category release, never queued):
  refused in an agent's session after its plan, and by the owner guard; `brain release status` names it as the
  tag's next move. The release that adds it is itself tagged by hand (docs/release.md, « 3. The tag »;
  `wi-brain-release-tag-command`).
