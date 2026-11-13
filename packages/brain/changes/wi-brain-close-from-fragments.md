section: Added

- `brain wave close-merged X.Y.Z [--repo NAME]... [--repo-dir D]... [--since REF] [--until REF] [--write] [--json]`
  (`wi-brain-close-from-fragments`, `brain.closemerged`): the items a wave's merged PRs deliver, closed from the PRs
  themselves. In each repo of the project, the PRs merged on the default branch since the last release tag before
  X.Y.Z (git alone: GitHub's merge and squash commits), each mapped to its items by the changelog fragment it added
  (`changes/` or `packages/<name>/changes/`: `<item>.md`, `<item>-<section>.md`) or an item id in its title, a revert
  taking its PR out; the plan closes each open one done with `--pr "<repo> #N"`, the PR's title as the outcome and its
  merge's date, and `--write` writes it (refused while a repo could not be read). It lists the items already closed,
  the PRs and fragments that name no item and the wave's open items no merged PR names.
