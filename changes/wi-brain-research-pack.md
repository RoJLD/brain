section: Changes

- The research pack's gates moved out of `research_graph.validate`'s core into `research_graph.research_pack`
  (`wi-brain-research-pack`, spec-brain-typology-packs E5): the experiments' folders and their Experiment nodes, the
  kanban, a staged experiment's pre-registration, the hypothesis graph's wiring and advisories, and the Edge gates.
  Their behaviour is unchanged (`research_graph check` runs the coverage, wiring and advisories as before, a project's
  own pre-commit the notebook gates) and every name stays importable from `research_graph.validate`, the same
  objects; a monkeypatch now reaches the moved callers through `research_graph.research_pack`'s names, no longer
  validate's. `research_pack.GATES` names them by kind. A new research rule lands in the pack, never in the core.
