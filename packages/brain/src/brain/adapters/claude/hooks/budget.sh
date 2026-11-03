#!/usr/bin/env bash
# PostToolUse: the budget watch (hooks/budget.py, brain.budget): at 80 % and at 100 % of the brief's context budget
# or of the recorded estimate of the items the brief names, one notice each as hook context; it never blocks.
# Fast path in bash builtins (no process started): Python sets the mtime of <BRAIN_HOME>/budget/<session>.mark in the
# future, when the next check is due; while the mark is newer than the transcript its line 1 names, it stops.
# Uses $BRAIN_PYTHON, else the brain command's venv (<BRAIN_HOME>/venv: the installed engine), else python3, else
# python, skipping the Windows Store stubs; without a Python 3 it does nothing.
# BRAIN_BUDGET_WATCH=0 turns it off.
[ "${BRAIN_BUDGET_WATCH:-1}" = "0" ] && exit 0
IFS= read -r -d '' payload
re_sid='"session_id"[[:space:]]*:[[:space:]]*"([A-Za-z0-9._-]+)"'
sid=
[[ $payload =~ $re_sid ]] && sid=${BASH_REMATCH[1]}
[[ -z $sid ]] && exit 0
mark="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}/budget/$sid.mark"
if [[ -f $mark ]]; then
  IFS= read -r watched < "$mark"
  [[ -n $watched && $mark -nt $watched ]] && exit 0
fi

root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
home="${BRAIN_HOME:-$HOME/.brain}"
for py in "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python; do
  [ -n "$py" ] || continue
  path=$(command -v "$py" 2>/dev/null) || continue
  case "$path" in *WindowsApps*) continue ;; esac
  "$path" -X utf8 -I "$root/hooks/budget.py" PostToolUse <<<"$payload" 2>/dev/null
  exit 0
done
exit 0
