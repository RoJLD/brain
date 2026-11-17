section: Added

- `brain audit` reports a stale waiver: `waive.stale` (P2, never in the scout; ruleset 13) is a glob of a repo's
  `waive:` in `projects.yaml` that matches no file of the repo's tree. Remove it, or fix the glob to the files it
  means (docs/tests-graph.md, « What the audit measures »). The trend leaves it out of its past weeks.
