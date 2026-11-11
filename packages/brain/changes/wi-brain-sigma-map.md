section: Added

- The module registry's map of realisations (`wi-brain-sigma-map`, `brain.modulemap`): a `modules.yaml` entry can
  carry hand-written fields beside the document ones (`wanted`, `capabilities`, `depends_on`, `uses`, `ai`,
  `realized_by` with each realisation's project, kind, what, paths, ref, licence, state, contract, ships_in and
  retire, and `map_review`), described by the new registered format `schemas/modules.schema.json`. On the store that
  keeps the registry, `brain modules --check` (exit 1) and `brain check` (a warning) validate an entry that carries
  them, and only such an entry: its shape, the module ids it names, the capabilities (`tiers.yaml`), the projects
  (the projects registry), the paths at their ref when the project's checkout is on the machine, a wanted module with
  neither a realisation nor an open item; a wanted module with no item done or open 90 days after its `since` is a
  warning. The view gains the realisations, the map's gaps and the declared dependencies still to classify, and
  `brain modules --json` gains `map` and `map_problems`. A registry with no entry that carries the map, and its view,
  are unchanged.
