#!/usr/bin/env bash
# SessionStart: one line for the session's project saying whether its resume pack is written (brain resume --write,
# <BRAIN_HOME>/resume/<project>.md) and how old it is, never the pack itself (hooks/resume.py, brain.resume.hook_main);
# nothing outside a project with notes/graph; never fails (errors go to <BRAIN_HOME>/ledger/errors.log). Uses the
# brain command's venv (PyYAML), else $BRAIN_PYTHON, python3 or python, skipping the Windows Store stubs; without a
# Python 3 it does nothing.
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
home="${BRAIN_HOME:-$HOME/.brain}"

for py in "$home/venv/Scripts/python.exe" "$home/venv/bin/python" "${BRAIN_PYTHON:-}" python3 python; do
  [ -n "$py" ] || continue
  path=$(command -v "$py" 2>/dev/null) || continue
  case "$path" in *WindowsApps*) continue ;; esac
  "$path" -X utf8 -I "$root/hooks/resume.py" "${1:-SessionStart}" 2>/dev/null
  exit 0
done
exit 0
