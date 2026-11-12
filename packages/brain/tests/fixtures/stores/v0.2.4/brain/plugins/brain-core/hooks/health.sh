#!/usr/bin/env bash
# SessionStart: the watched stacks that are down (hooks/health.py, brain.stacks.hook_main), as hook context; prints
# nothing when all is well, nothing for an on-demand stack that is simply stopped, never fails (errors go to
# <BRAIN_HOME>/ledger/errors.log). Bounded to ~1.5 s of checks. Uses the brain command's venv (PyYAML), else
# $BRAIN_PYTHON, python3 or python, skipping the Windows Store stubs; without a Python 3 it does nothing.
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || { selftime_bash() { :; }; brain_python() { return 1; }; }; } 2>/dev/null  # brain_t0, selftime_bash, brain_python
root="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/..}"
home="${BRAIN_HOME:-$HOME/.brain}"

brain_python "$home/venv/Scripts/python.exe" "$home/venv/bin/python" "${BRAIN_PYTHON:-}" python3 python && BRAIN_HOOK_T0=$brain_t0 "$brain_py" -X utf8 -I "$root/hooks/health.py" "${1:-SessionStart}" 2>/dev/null
exit 0
