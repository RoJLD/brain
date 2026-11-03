#!/usr/bin/env bash
# Run brain's zero-token capture (hooks/capture.py) for the hook event in $1, the hook's JSON on stdin.
# Uses $BRAIN_PYTHON, else python3, else python, skipping the Windows Store stubs; without a Python 3 it does nothing.
# It never blocks or slows the session down: prints nothing, always exits 0. BRAIN_CAPTURE=0 turns it off.
[ "${BRAIN_CAPTURE:-1}" = "0" ] && exit 0
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

for py in "${BRAIN_PYTHON:-}" python3 python; do
  [ -n "$py" ] || continue
  path=$(command -v "$py" 2>/dev/null) || continue
  case "$path" in *WindowsApps*) continue ;; esac
  "$path" -I "$root/hooks/capture.py" "$@" >/dev/null 2>&1
  exit 0
done
exit 0
