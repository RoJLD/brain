section: Upgrade

**Check the derived deny terms before the next push to a public repo**: the public check now refuses the names your
registries declare (machines, people, projects, specs, modules: README, « The deny terms derived from the
registries »). Run `brain check --public` in each public checkout; a name that is public (a third-party tool a project
reads, an engine capability a module is named after) goes to `config.json` `public.public_names` with its reason,
by a PR, and `public.derive` narrows the sources. Then `brain check --public --refresh` restamps.
