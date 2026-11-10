section: Added

- The feature matrix split by repo: each repo's `FEATURES.md` lists the features whose `repo` it is, and a checkout
  that is a clone of a public repo (one of its git remotes is in `config.json` `public.repos`) gets the public render
  (`brain features render --repo R --out <checkout>/FEATURES.md --write`): a feature's new optional props
  `public_title` and `public_id` stand for a title or an id that names the owner or a private project (the graph
  keeps both), only the repo's own code, tests and docs are shown, and no spec, ADR or work item of the private
  brain; the render warns about what `brain check --public` would still refuse in it. `brain audit` (check
  `features.md`) compares each repo's file with its own render, public or not, and its fix names the `--repo`/`--out`
  command for a repo other than the store's; in a public clone that check accepts the full render too, unless the new
  optional `config.json` key `features.public_strict` is true (the owner's opt-in, default false: nothing that passed
  is newly refused). `brain features set` checks a `public_id` is a feature id no other node
  or feature has (`wi-brain-features-repo-split`).
