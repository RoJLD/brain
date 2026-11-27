section: Changes

- The merge gate per repo, from config.json's new `merge.repos.<owner/name>` (docs/merge-driver.md): `ci: false`
  declares a repo without CI, whose head reporting no check no longer refuses its PR in `brain ship`: the merger's own
  local checks (the views regenerated or the store checked, the targeted tests) stand for the CI, the gate's stamp
  records it, and no CI is awaited after a catch-up; `brain merge-ready` alone still blocks it, marked `local`
  (`wi-brain-gate-local-checks-no-ci`). `review_exempt: [globs]` lists the files that are no code (records, docs,
  views): a PR every file of which one covers needs no review stamp in `brain merge-ready`, `brain ship` and `brain
  gate`, and one file outside makes it a code PR (`wi-brain-gate-review-scope`). A repo the section does not name
  keeps today's rules.
- The merge gate's body check of a private repo's PR refuses a secret only: its title and body may name its owner,
  projects and hosts; a public repo's are checked as before (`wi-brain-gate-body-terms-public-only`).
