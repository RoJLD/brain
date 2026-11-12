section: Changes

- The legacy fallback of the graph engine is gone (`wi-brain-public-deny-derived`): without the `research_graph`
  package in brain's venv, or with `$BRAIN_GRAPH_PYTHON` set, brain runs `python -m research_graph` in that Python
  (else this one) and no longer looks for an older copy in a registered project. The examples of the docs and the
  tests name invented projects, and brain lint's rule commands no longer count a private project's command.
