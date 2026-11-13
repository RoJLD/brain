section: Added

- The owner's gestures declared once (`brain.gestures`, `wi-brain-owner-only-registry`): every command or flag only
  the owner runs (`brain usage allow`, `brain handover root`, `brain schedule install --apply`, `brain ipc
  otel-headers`, `brain vault open`, `drill`, `device init`, `device forget-previous`, `reseal --apply`, `brain
  update`, `brain uninstall --apply`, `brain queue apply`, `install.ps1 -Apply`) is one list that the owner guard and
  the command line read; a test checks that each is refused to an agent's session, by the guard, guard.sh's
  pre-filter and the command line, and listed in docs/guards.md. The guard finds a gesture however brain is run
  (`python -X utf8 -m brain`, `-mbrain`, `-Imbrain`, `uv run brain`, brain's options or their prefixes first, options
  between its words, a flag's prefix), where `brain usage allow` and `schedule install --apply` escaped it before. The
  new optional config.json key `guards.owner_strict` (default false) adds the refusals this release brings to what
  passed before: at the guard, `brain vault reseal --apply` and the gestures whose commands refuse themselves already
  (`vault open`, `drill`, `device init` and `forget-previous`, `update`, `uninstall --apply`, `queue apply`); at the
  command line, exit 2, `brain usage allow`, `brain schedule install --apply` and `brain vault reseal --apply` in an
  agent's session.
