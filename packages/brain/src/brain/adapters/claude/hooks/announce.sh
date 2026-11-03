#!/usr/bin/env bash
# SessionStart: announce the decisions the owner answered that the session's project has not integrated yet
# (hooks/announce.py, brain.decisions.announce), as hook context; prints nothing when there are none.
# Uses $BRAIN_PYTHON, else the brain command's venv (<BRAIN_HOME>/venv: the installed engine), else python3, else
# python, skipping the Windows Store stubs; without a Python 3 it does nothing.
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || selftime_bash() { :; }; } 2>/dev/null  # brain_t0, selftime_bash
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

home="${BRAIN_HOME:-$HOME/.brain}"
for py in "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python; do
  [ -n "$py" ] || continue
  path=$(command -v "$py" 2>/dev/null) || continue
  case "$path" in *WindowsApps*) continue ;; esac
  BRAIN_HOOK_T0=$brain_t0 "$path" -X utf8 -I "$root/hooks/announce.py" "${1:-SessionStart}" 2>/dev/null
  exit 0
done
exit 0
