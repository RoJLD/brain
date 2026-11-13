section: Added

- The lite suite (`wi-brain-lite-suite`, marker `lite`: `pytest packages/brain -m lite`): the stranger test's Lite
  scenario run on the checkout's engine (checked) with `docker`, `podman` and `gh` replaced by shims that leave a
  mark, the proxies pointed at a listener that counts connections, no `BRAIN_GRAPH_PYTHON` and `brain refresh
  --offline`; then an ADR, the records' check, a sync, the capture hook. What each step wrote is read back (journal,
  decision log, item, DDR, the views regenerated, the derived links, the session event), with no mark and no
  connection: the core keeps its guards, records, decision queue, backlog, journal, ADRs, rule injection, capture
  and views. In the CI a missing `brain` launcher fails it rather than skipping it.
