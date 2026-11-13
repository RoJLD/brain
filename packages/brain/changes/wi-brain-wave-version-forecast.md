section: Added

- `brain next` and `brain wave check X.Y.Z` say the release the wave will be: the patch it is named for or a minor,
  the first merged PR that tipped it and the reasons (a schema that moved, an Upgrade step beyond the standard ones),
  from the release preview of the engine checkout's `origin/main`, so the version and the wave's name are decided
  before the version PR. `release_check.py --preview` gains `--ref REF` (preview a commit, the working tree left
  alone) and `--json`. Advisory: no exit code changes (wi-brain-wave-version-forecast).
