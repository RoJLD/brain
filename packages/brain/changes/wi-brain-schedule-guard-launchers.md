section: Added

- The owner's gestures matched wide (`wi-brain-schedule-guard-launchers`): under config.json `guards.gestures_wide:
  true` (off by default), the owner guard refuses `brain schedule install --apply` (and every gesture of
  `brain.gestures`) through words it cannot resolve (`brain schedule install $FLAG`, `brain schedule $x`, `brain $x`,
  `& $brain ...`, PowerShell's `@a` and `@('--apply')`), through Python's inline code that drives brain's modules
  (`python -X utf8 -c "... main(['schedule', 'install', '--apply'])"`, the code's own arguments read too), and a call
  that clears an agent session's markers (`CLAUDECODE= ...`, `env -u`, `unset ${!CLAUDE*}`, `export -n`,
  `$env:CLAUDECODE = ''`, `Remove-Item Env:CLAUDE*`, .NET's environment calls); `brain usage allow` and `brain vault
  reseal --apply` then refuse themselves in an agent's session as under `guards.owner_strict`. guard.sh's pre-filter
  reads a command's quoted and escaped words (`b\rain`, `"us"age`, `ins''tall`) and starts Python for a brain command
  with a word it may not resolve. The MCP server matches wide under the same key (docs/guards.md, « The owner's
  gestures »).
- Under config.json `guards.gestures_session_markers: true` (optional, off by default), the gestures that act
  (`schedule install --apply`, `update`, `uninstall --apply`, `queue apply`, `handover root`) refuse themselves while
  any agent marker is set: `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `BRAIN_AGENT_SESSION` or
  a variable Claude Code sets for each session (`CLAUDE_CODE_SESSION_ID`, `CLAUDE_PID`...), not only `CLAUDECODE`
  (`brain.gestures.agent_session`, `brain.detail.refused`); a configuration variable such as `CLAUDE_CODE_USE_BEDROCK`
  in the owner's terminal is none.
