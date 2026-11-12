section: Added

- `public.deny.repos` generated from the scope tree (`wi-brain-deny-from-tree`), opt-in by `config.json`
  `public.deny_from_tree: true`: the projects under a class floor of `private` or stricter (their names and their repos'
  names, a repo of `public.repos` left out) join the hand list that `brain check --public` and the public guard read, so
  a newly placed private project is denied without a hand edit; `brain scopes --deny` prints them. With it on, a
  `scopes.yaml` or registry that cannot be read makes the public guard refuse.
