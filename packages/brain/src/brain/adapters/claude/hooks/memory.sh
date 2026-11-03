#!/usr/bin/env bash
# Memory shared across machines by a reviewed PR (hooks/memory.py, brain.memory).
# SessionEnd: Python decides in a few milliseconds whether a memory note changed since the last sync (mtime and size)
# or the last pull is older than BRAIN_MEMORY_PULL_HOURS and, if so, starts the sync detached and returns (fetch main,
# import what only main changed, secret scan, export what only this machine changed to memory/<machine>/<date> and its
# PR; never main). Prints nothing, never fails (errors go to <BRAIN_HOME>/ledger/errors.log).
# SessionStart: prints <BRAIN_HOME>/memory-sync/alert.txt (a refused export, a conflict, a failure, a job that died)
# as hook context, in bash builtins; nothing when there is none.
# BRAIN_MEMORY_SYNC=0 turns both off. Uses the brain command's venv, else $BRAIN_PYTHON, python3 or python, skipping
# the Windows Store stubs; without a Python 3 it does nothing.
[ "${BRAIN_MEMORY_SYNC:-1}" = "0" ] && exit 0
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || selftime_bash() { :; }; } 2>/dev/null  # brain_t0, selftime_bash
home="${BRAIN_HOME:-$HOME/.brain}"

if [ "${1:-}" = "SessionStart" ]; then
  alert="$home/memory-sync/alert.txt"
  [ -s "$alert" ] || { selftime_bash "hook memory SessionStart [bash]"; exit 0; }
  text= bs='\' q='"'
  while IFS= read -r line || [ -n "$line" ]; do  # a JSON string: CR dropped, \ and " escaped, tabs to spaces
    line=${line//$'\r'/}
    line=${line//"$bs"/"$bs$bs"}
    line=${line//"$q"/"$bs$q"}
    line=${line//$'\t'/ }
    text+="$line${bs}n"
  done < "$alert"
  printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$text"
  selftime_bash "hook memory SessionStart [bash]"
  exit 0
fi

root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
for py in "$home/venv/Scripts/python.exe" "$home/venv/bin/python" "${BRAIN_PYTHON:-}" python3 python; do
  [ -n "$py" ] || continue
  path=$(command -v "$py" 2>/dev/null) || continue
  case "$path" in *WindowsApps*) continue ;; esac
  BRAIN_HOOK_T0=$brain_t0 "$path" -X utf8 -I "$root/hooks/memory.py" session-end >/dev/null 2>&1
  exit 0
done
exit 0
