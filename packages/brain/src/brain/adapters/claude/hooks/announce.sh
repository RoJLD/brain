#!/usr/bin/env bash
# SessionStart: announce the decisions the owner answered that the session's project has not integrated yet
# (hooks/announce.py, brain.decisions.announce), as hook context; prints nothing when there are none.
# Uses $BRAIN_PYTHON, else python3, else python, skipping the Windows Store stubs; without a Python 3 it does nothing.
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

for py in "${BRAIN_PYTHON:-}" python3 python; do
  [ -n "$py" ] || continue
  path=$(command -v "$py" 2>/dev/null) || continue
  case "$path" in *WindowsApps*) continue ;; esac
  "$path" -I "$root/hooks/announce.py" "${1:-SessionStart}" 2>/dev/null
  exit 0
done
exit 0
