#!/usr/bin/env bash
# Run brain's zero-token capture (hooks/capture.py) for the hook event in $1, the hook's JSON on stdin.
# Uses $BRAIN_PYTHON, else the brain command's venv (<BRAIN_HOME>/venv: the installed engine), else python3, else
# python, skipping the Windows Store stubs; without a Python 3 it does nothing.
# It never blocks or slows the session down: prints nothing, always exits 0. BRAIN_CAPTURE=0 turns it off.
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || selftime_bash() { :; }; } 2>/dev/null  # brain_t0, selftime_bash
[ "${BRAIN_CAPTURE:-1}" = "0" ] && exit 0
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

home="${BRAIN_HOME:-$HOME/.brain}"
for py in "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python; do
  [ -n "$py" ] || continue
  path=$(command -v "$py" 2>/dev/null) || continue
  case "$path" in *WindowsApps*) continue ;; esac
  BRAIN_HOOK_T0=$brain_t0 "$path" -X utf8 -I "$root/hooks/capture.py" "$@" >/dev/null 2>&1
  exit 0
done
exit 0
