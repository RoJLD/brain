section: Added

- A plugged project's cockpit panels and tabs, declared as data (`wi-brain-command-plugins-cockpit`,
  `brain.plugin_panels`): its plugin's `COCKPIT` mapping names each panel's rows (a JSON file under the project's root,
  or a `module:attr` callable), its columns, sorts, filters and help, and its tabs. `brain tui` draws each panel as one
  of its own tables (search, sorts, filters, saved views, columns, palette, detail, `--once`), its tab after Resources
  with no number (`--tab <project>`); its rows are read at the first read and at each probe. An unknown key is kept and
  noted, a plugin that cannot load is noted, never an error. `brain tui --tab` now takes a plugged project's tab too.
