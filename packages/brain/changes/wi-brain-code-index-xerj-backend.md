section: Added

- xerj, an opt-in backend of the code index, never chosen by default (GitNexus stays the search authority, CBM-1): `brain
  index --backend xerj` reads each declared repo's branch head with `git archive` into
  `$BRAIN_HOME/code-index/xerj/snapshots` and runs `xerj autoindex --no-graph` on it under the repo's prefix (two
  repos sharing one are refused), read from its `xerj-done` line (exit 0 and 3 finished, 4 a decision reported, never
  answered; no line a failure), recorded in `$BRAIN_HOME/code-index/xerj/record.json`; `brain health code-index` says
  its line once it indexed a repo, never counted, and an installed xerj never lifts the declaration error of repos
  with no counted backend; `brain.codebackends.search(query, repo, k, backend="xerj")` returns ranked rows (rank,
  path, line, name, kind, score) from `xerj search --json`. Its node is a stack whose start and stop are the new
  `brain index --backend xerj --serve` and `--stop`: detached on 127.0.0.1:9200, TLS and keys off, lexical, its data
  under BRAIN_HOME; a port held by another service is left alone; the stop signals only the process of the engine's
  binary that its lock names (SIGTERM then SIGKILL; forced at once on Windows, where a detached node has no console).
  Every call runs with `XERJ_DISABLE_FEEDBACK=true`, `XERJ_NO_AUTOSTART=1` and `HF_HUB_OFFLINE=1`; never `xerj init`.
  The binary is built by the owner from xerj's public main (`docs/code-index.md` « xerj »; tier `code-index-xerj`)
  (`wi-brain-code-index-xerj-backend`).
