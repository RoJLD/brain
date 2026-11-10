section: Added

- Read commands, so sessions stop reading a brain's files by hand (`brain.reads`): `brain item show ID [--history]`
  (the item's props in full, its edges both ways, the ids its props name, its blockers, the ADRs behind it (direct,
  inherited, superseded) and its specs, the DDRs that name it; `--history` its changes from git), `brain items` with
  filters (`--status`, `--all`, `--priority`, `--wave X.Y.Z|ID`, `--milestone`, `--prop K[=TEXT]`, `--text`,
  `--type`, `--repo`, `--limit`), `brain adr show REF [--titles]` (an ADR's text by id, title or the start of its id,
  else the ADRs that decide a node such as a rule), `brain spec show REF [--section N | --toc]` (a Spec node, a Doc id
  or a path) and `brain journal last [N] [--titles]`; each takes `--json` and loads the graph in brain's own process
  (no `research_graph` on the PATH). A PreToolUse hint (`readhint.sh`, `brain.readhint`), never a refusal: when Read,
  Grep or a shell command that reads targets a registered brain's graph YAML, decision log, journal or generated
  views, one line of hook context names the command that answers; bash builtins until the call names one of those
  files, `BRAIN_READ_HINT=0` turns it off. The close-item procedure, the brief (`brain brief`, « How to start ») and
  the generic `CLAUDE.md` template name the commands (`wi-brain-read-commands`).
