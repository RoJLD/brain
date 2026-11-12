section: Added

- The cockpit's settings tab (the comma, `wi-brain-tui-settings`): every setting with its value, the file or variable
  it comes from and how it changes, page by page (Cockpit, Identity, Brain, Permissions, Setup; `brain.settings`).
  The cockpit's own settings in `<BRAIN_HOME>/tui.json` are edited there with Enter and apply at once: the theme, the
  timezone, the language, each panel's free title, and two new ones, `refresh` and `probe` (how often the files are
  checked and the probes run; `--refresh` and `--probe` now win for one launch only). The brain's settings (identity,
  `$BRAIN_HOME`, `config.json`, the registry, the engine pin, the profile, the stacks, the notification routes, the
  code index, the scope types, `permissions.yaml`, Claude Code's settings) are shown with the command that changes
  each and never written from there; a secret is named, never shown. `brain tui --once --tab settings` prints the
  pages.
