section: Added

- Graph templates as layers (`wi-brain-graph-templates`): research_graph's catalogue of the layers real stores have
  proven (work, decisions, records, lessons, ideas, research, data, code, docs_tests, features, operations, fleet,
  rules, delivery), each a layer file with its types, edges and their endpoints, statuses, mode, commands, views,
  checks, GitNexus projection and fictitious examples. `research_graph layers` lists them (and the store's), `show`
  one, `compose` the schema.yaml they make (`templates:` records each layer's version, `endpoints:` the edges'
  allowed types), `add` layers to a store by a plan (a diff of schema.yaml that keeps its text and comments, then
  `--write`), `propose` the layers a typology's stage proposes; `research_graph init --layers` composes a new store's
  schema. `research_graph check` refuses an edge outside its declared endpoints (a schema without `endpoints:` is
  checked as before). A `brain init` template's graph may give `layers:` (the catalogue's and the template's own
  `layers/<name>.yaml`) instead of `schema: default`. The brain's base schema and research_graph init's default are
  unchanged: a test keeps them equal to their layers composed.
