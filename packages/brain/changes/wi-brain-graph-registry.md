section: Added

- `brain graphs [--project P | --all] [--json]`: every graph of a project, or of every project, in one list, at zero
  token and writing nothing (`docs/graphs.md`): each store's layers (the store's own `layers:` then the catalogue's;
  the recorded and the catalogue's version; written, generated or mixed; node and edge counts by type; the last
  commit of their files and whether one has uncommitted changes; query and impact entries; what reads them) and the
  catalogue's layers it lacks with the command that adds them; its overlays; its code index per backend against the
  branch head, from the records and git alone; its `docgraph/` documents (a read project's pinned copy under that
  project with `--all`); the source files beside the graph. Its `--json` keys are a public contract (`v` 1, keys
  only added): `v, scope, projects` (`wi-brain-graph-registry`).
