section: Changes

- `brain update` installs the new version beside the running one, in `<BRAIN_HOME>/venvs/vX.Y.Z` (a venv made from
  the interpreter the active one was made from), runs a health gate there (`brain --version`, `brain doctor --quick`
  in the brain's root, the guards letting `git status` pass), and only then switches `<BRAIN_HOME>/venv`, now a
  link to the active slot (a junction on Windows, a symlink elsewhere), which the launcher on the PATH follows; a
  watchdog runs `brain --version` through both after the switch and switches back to the previous slot when one
  fails. The first
  such update moves the installer's real `venv` folder into `venvs/v<its version>`. Three slots are kept. The hooks,
  the installer and the shim keep reading `<BRAIN_HOME>/venv`; a new home store, `venvs` (sealed, install), is
  declared (`wi-brain-update-blue-green`; the layout of `ddr-2026-11-12-blue-green-engine-slots`).
