section: Added

- Dependency probes, loud fallbacks (`wi-brain-dependency-probes`, `brain.depprobes`): `config.json` `probes`
  declares a token-free probe per external dependency of a capability, with the machines it runs on, of four kinds
  (`file-age`, `json-age`, `command` with no shell and its output never shown, `http` with no header and its URL
  never shown), each with its own timeout (a command past it is killed with every process it started, and a probe
  still running never holds the process at its exit). The alerts pass runs this machine's probes when the brain's own project is
  in scope and raises `probe:<name>` at the probe's level for each one that is not OK (sent once, resolved once, by
  the pass's notify path); each run is recorded in `<BRAIN_HOME>/probes/state.json` (state, last OK, since).
  `brain status` shows a probes row once one runs here, the cockpit's health panel a line; `brain probes [--last |
  --list | --kinds] [--json]` runs or lists them; `brain config --check` checks the declarations.
