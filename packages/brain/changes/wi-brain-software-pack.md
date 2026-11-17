section: Added

- The software pack extracted from the core (`wi-brain-software-pack`, TYPO-1): a project's `repos`, `audit`,
  `code_index` and `production` may be grouped under `software:` (the top level stays an alias; a key in both places is
  an error, an unknown key under `software:` a note in read mode), read alike by every command and guard; `brain audit`
  takes a project's root as a code repo by default, and the scout runs, only when the software pack applies to its
  kinds (none declared, one unknown, or one meeting the pack): a `strategy` or `creation` project is audited for no
  code repo, said in the report (`not_software` in `--json`), unless it declares `repos`
  ([docs/typologies.md](docs/typologies.md#the-software-pack)).
