section: Changes

- The research pack's gates moved out of `research_graph.validate`'s core into `research_graph.research_pack`
  (`wi-brain-research-pack`, spec-brain-typology-packs E5): the experiments' folders and their Experiment nodes, the
  lab notebook and the kanban, a staged experiment's pre-registration, the hypothesis graph's wiring and advisories,
  and the Edge gates. Their behaviour is unchanged (`research_graph check` runs them as before) and every name stays
  importable from `research_graph.validate`; `research_pack.GATES` names them by kind. A new research rule lands in
  the pack, never in the core.
