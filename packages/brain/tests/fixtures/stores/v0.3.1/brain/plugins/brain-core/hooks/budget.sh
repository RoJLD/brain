#!/usr/bin/env bash
# PostToolUse: the budget watch (hooks/budget.py, brain.budget): at 80 % and at 100 % of the brief's context budget
# or of the recorded estimate of the items the brief names, one notice each as hook context; it never blocks.
# Fast path in bash builtins (no process started): Python sets the mtime of <BRAIN_HOME>/budget/<session>.mark in the
# future, when the next check is due; while the mark is newer than the transcript its line 1 names, it stops.
# Uses $BRAIN_PYTHON, else the brain command's venv (<BRAIN_HOME>/venv: the installed engine), else python3, else
# python, skipping the Windows Store stubs; without a Python 3 it does nothing.
# BRAIN_BUDGET_WATCH=0 turns it off.
[ "${BRAIN_BUDGET_WATCH:-1}" = "0" ] && exit 0
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || { selftime_bash() { :; }; brain_python() { return 1; }; }; } 2>/dev/null  # brain_t0, selftime_bash, brain_python
IFS= read -r -d '' payload
re_sid='"session_id"[[:space:]]*:[[:space:]]*"([A-Za-z0-9._-]+)"'
sid=
[[ $payload =~ $re_sid ]] && sid=${BASH_REMATCH[1]}
[[ -z $sid ]] && { selftime_bash "hook budget [bash]"; exit 0; }
mark="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}/budget/$sid.mark"
if [[ -f $mark ]]; then
  IFS= read -r watched < "$mark"
  [[ -n $watched && $mark -nt $watched ]] && { selftime_bash "hook budget [bash]"; exit 0; }
fi

root="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/..}"
home="${BRAIN_HOME:-$HOME/.brain}"
brain_python "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python && BRAIN_HOOK_T0=$brain_t0 "$brain_py" -X utf8 -I "$root/hooks/budget.py" PostToolUse <<<"$payload" 2>/dev/null
exit 0
