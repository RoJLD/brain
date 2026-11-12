#!/usr/bin/env bash
# Run brain's zero-token capture (hooks/capture.py) for the hook event in $1, the hook's JSON on stdin.
# Uses $BRAIN_PYTHON, else the brain command's venv (<BRAIN_HOME>/venv: the installed engine), else python3, else
# python, skipping the Windows Store stubs; without a Python 3 it does nothing.
# It never blocks or slows the session down: prints nothing, always exits 0. BRAIN_CAPTURE=0 turns it off.
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || { selftime_bash() { :; }; brain_python() { return 1; }; }; } 2>/dev/null  # brain_t0, selftime_bash, brain_python
[ "${BRAIN_CAPTURE:-1}" = "0" ] && exit 0
root="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/..}"

home="${BRAIN_HOME:-$HOME/.brain}"
brain_python "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python && BRAIN_HOOK_T0=$brain_t0 "$brain_py" -X utf8 -I "$root/hooks/capture.py" "$@" >/dev/null 2>&1
exit 0
