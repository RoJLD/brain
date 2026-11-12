section: Added

- The scope tree as data (`wi-brain-scope-tree`): `parent:` places a project of `projects.yaml` (a read-only project
  and a tenant mount too) under a container of the new optional `scopes.yaml` (beside `config.json`; `config.json`
  `scopes`, `$BRAIN_SCOPES`) or under another project; `config.json` `scope_types` renames or adds a type of the
  catalogue. `brain check --all` checks the tree (a known parent, no cycle, ids unique across projects and containers,
  a known and accepted type, a class floor never under an ancestor's, a warning past six levels); `brain scopes`
  prints it; `brain status --scope REF` shows a node's subtree (`global` is `--all`); `brain sync` writes
  `notes/scopes_graph.md`. Without `scopes.yaml` and `parent:`, everything stays flat under Global, as before.
