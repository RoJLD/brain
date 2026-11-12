section: Changes

- The installer says whether it runs from the commit the signed tag names (`verify   this installer runs from that
  commit`, else a `note` with its own HEAD and `+changes` when tracked files differ): the tag's check runs inside the
  tag's own code, so it cannot vouch for that code; a statement, never a refusal. `docs/identity.md` (« Signed
  releases ») gives the offline checks a brain's own bootstrap runs on its engine clone before running it: the tag
  annotated and signed by a key of `allowed_signers`, the clone's HEAD its commit, no tracked file changed
  (`wi-brain-install-verify-tag`).
