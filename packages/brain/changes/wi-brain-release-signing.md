section: Added

- Signed engine releases (STD-3): `brain update` and the installer verify a release tag with `git verify-tag` before
  installing it, against `allowed_signers`, a file `brain identity allowed-signers --write` generates beside
  `config.json` from `members.yaml`'s new `releaser` role (namespace `git`). A verified tag is installed by the commit
  it names, so it cannot move between the check and the install. Both say the verification either way and refuse
  nothing by default; `config.json` `engine.verify_tags: true`, an optional key, refuses an unsigned tag, one signed
  by another key, or one that cannot be verified. `brain check` warns when `allowed_signers` is no longer what
  `members.yaml` gives. CI's `release-tag` job says whether the tag is signed, advisory. The release checklist signs
  each tag (`git tag -s`, docs/release.md « 3. The tag »); the owner's key and its setup: docs/identity.md « Signed
  releases » (`wi-brain-release-signing`).
