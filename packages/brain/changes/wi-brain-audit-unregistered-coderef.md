section: Changes

- `brain audit` reports an active CodeRef of a repo no project of the registry registers as `coderef.dangling` (P0,
  ruleset 11), instead of listing it as not measured; `brain check --all` refuses it (a warning in a brain's own root
  without `--all`). A CodeRef of another project's repo, or of the project's own repo not cloned here, stays not
  measured (`wi-brain-audit-unregistered-coderef`).
