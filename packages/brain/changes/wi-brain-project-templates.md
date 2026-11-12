section: Added

- A project's brain by profile (`wi-brain-project-templates`): `brain init --template cli|local-client|service|
  data-pipeline|research [--stage prototype|mvp|v1|scale]`. Each is the generic brain, its files unchanged, plus the
  profile's standards selection in `projects.yaml` (`standards: {profiles, stage}`), the CI jobs (the tests with
  their coverage, compat-prev: the last tag's tests on the PR's code), the test harness (a virtual clock, fault
  injection, the old formats' fixtures, with its own tests), the format registry's skeleton (`docs/formats.md`), an
  issue template and an ADR template, the boundary's rule for `.github/`, and the graph's layers for the profile.
  A template may `extends` one of the engine's and `append` a fragment to a file the base writes; the bases
  `_project` and `_software` are what the profiles extend. This adds to what `brain init` can write: the release
  that carries it is a minor one.
