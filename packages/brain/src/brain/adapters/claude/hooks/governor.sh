#!/usr/bin/env bash
# PreToolUse on a new session (mcp__*__start_session), a subagent (Agent, Task) and a workflow (Workflow): the
# governor's usage-enforce hook (hooks/governor.py, brain.governor). It reads the cached quota readings, the open
# sessions and brainstorms and the machine's committed memory; it asks the owner at WARN and refuses at CRITICAL, past
# a cap, or while the newest quota reading is stale. A decision is one JSON line on stdout; nothing else is printed.
# Uses $BRAIN_PYTHON, else the brain command's venv (<BRAIN_HOME>/venv: the installed engine), else python3, else
# python, skipping the Windows Store stubs. Without a Python 3, or on any error, the call goes through: it always
# exits 0, so the hook never breaks a session.
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || selftime_bash() { :; }; } 2>/dev/null  # brain_t0, selftime_bash
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
input=$(cat)
home="${BRAIN_HOME:-$HOME/.brain}"
for py in "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python; do
  [ -n "$py" ] || continue
  path=$(command -v "$py" 2>/dev/null) || continue
  case "$path" in *WindowsApps*) continue ;; esac
  printf '%s' "$input" | BRAIN_HOOK_T0=$brain_t0 "$path" -X utf8 -I "$root/hooks/governor.py" 2>/dev/null
  exit 0
done
exit 0
