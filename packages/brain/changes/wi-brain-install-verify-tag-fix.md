section: Fixes

- `brain update` and the installer no longer verify a release tag whose ref was pointed at another release's signed
  tag object (an account that can push but holds no key, rolling the machines back to an older signed tag): the
  signature covers the tag object, not the ref's name, so the object must now name the tag itself and a commit;
  otherwise the verdict is `misnamed`, refused under `engine.verify_tags` (`wi-brain-install-verify-tag`).
