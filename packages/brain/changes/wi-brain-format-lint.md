section: Added

- Format lints (`brain.formatlint`, `wi-brain-format-lint`): three rules, a path into the brain's home built outside
  `brain.paths`, a file of the home written around `brain.stateio`, a test reading the real home, read by two
  backends the owner switches on in `config.json`, both off by default (new optional keys
  `audit.format_lints_python`, `audit.format_lints_ast_grep`): the python one in the AST, the ast-grep one as YAML
  rules (`brain/lints/*.yml`) run by the `ast-grep` binary at its pinned version, 0.51.0 (N/A without it; the owner's
  install, the new `lint` extra). Switched on, `brain audit --diff` says what a change adds (info) and defers what a
  touched file had, never blocking. `brain lint formats [--backend B | --compare] [--json]` runs them over a repo
  and compares the backends (the occurrences each finds that the other does not, and their times).
