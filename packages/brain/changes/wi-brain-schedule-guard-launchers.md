section: Added

- The owner's gestures matched wide (`wi-brain-schedule-guard-launchers`): under config.json `guards.gestures_wide:
  true` (off by default), the owner guard refuses `brain schedule install --apply` (and every gesture of
  `brain.gestures`) through words it cannot resolve (`brain schedule install $FLAG`, `brain schedule $(echo install)
  --apply`, `& $brain ...`, PowerShell's `@rest` and `@('--apply')`) and through Python's inline code that drives
  brain's modules (`python -c "... main(['schedule', 'install', '--apply'])"`); guard.sh's pre-filter now reads a
  command's escaped words (`b\rain sched\ule install`) and starts Python for a brain usage, schedule, vault or queue
  command with such a word. The MCP server matches wide always (docs/guards.md, « The owner's gestures »).
