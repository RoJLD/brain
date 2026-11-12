section: Added

- **The deny terms derived from the brain's own registries** (`wi-brain-public-deny-derived`, brain.denylist): `brain
  check --public`, the commit and push guards and `brain boundary`'s readiness also refuse the names of the machines
  (`config.json` `hosts` and their aliases), the people (`identity`, `members.yaml`), the projects and their repos (the
  registry), the specs (`docs/specs`' file names) and the modules (the module registries' names, ids of 4 characters
  or more), from the day each is declared. `public.derive` picks the sources (absent: all; `[]`: none),
  `public.public_names` keeps a registry's public name out; `brain check --all` warns about a declared name no deny
  list holds. A term matches in every spelling of its separators (`a-b`, `a_b`, `a b`, `ab`), and every term is
  matched by one regex first, so the check stays fast with many terms.
