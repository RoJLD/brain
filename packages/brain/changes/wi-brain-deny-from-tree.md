section: Added

- `public.deny.repos` generated from the scope tree (`wi-brain-deny-from-tree`), opt-in by `config.json`
  `public.deny_from_tree: true`: the projects under a class floor of `private` or stricter, set by a container of
  `scopes.yaml` or by the project's own `classes: {floor}` in `projects.yaml` (which also binds its stores), join with
  their repos' names (a repo of `public.repos` left out) the hand list that `brain check --public` and the public guard
  read, so a newly placed private project is denied without a hand edit; `brain scopes --deny` prints them. With it
  on, a tree or registry that cannot be read, a named tree file missing, no tree, or an error of the tree's check makes
  the public guard refuse.
