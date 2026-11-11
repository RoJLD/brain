section: Added

- The release preview: CI's advisory `release-preview` job runs `release_check.py --preview --base origin/<target>` on
  every engine PR, the version policy applied as if the next release were a patch of the last tag. It names the
  registered schemas that moved since that tag and the pending Upgrade fragments' steps beyond the standard ones, says
  « a patch » or « a minor » and which reasons the PR carries, in the job's summary, and exits 0 whatever it says.
  `release-check` now also refuses, on every PR, a standard step that two pending Upgrade fragments ask, so a PR's
  fragment never copies the standard steps again (`wi-brain-release-preview`, docs/release.md « The release preview »).
