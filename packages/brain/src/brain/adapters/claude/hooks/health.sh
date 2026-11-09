#!/usr/bin/env bash
# SessionStart: the watched stacks that are down and a silent alerts pass (hooks/health.py, brain.stacks.hook_main,
# brain.schedule's dead-man), as hook context; prints
# nothing when all is well, nothing for an on-demand stack that is simply stopped, never fails (errors go to
# <BRAIN_HOME>/ledger/errors.log). Bounded to ~1.5 s of checks. Uses guard.sh's interpreter, in its order, so that
# what it says of the guards is what they run on: $BRAIN_PYTHON, else the brain command's venv (PyYAML), else python3
# or python, skipping the Windows Store stubs. Without a Python 3 that imports brain it says
# the guards cannot run (COMPAT-4, wi-brain-guards-fail-closed); health.py says when config.json makes them refuse.
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || { selftime_bash() { :; }; brain_python() { return 1; }; }; } 2>/dev/null  # brain_t0, selftime_bash, brain_python
root="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/..}"
home="${BRAIN_HOME:-$HOME/.brain}"

brain_python "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python && BRAIN_HOOK_T0=$brain_t0 "$brain_py" -X utf8 -I "$root/hooks/health.py" "${1:-SessionStart}" 2>/dev/null && exit 0
# no Python, or one that cannot import brain: the guards cannot run either (guard.sh refuses git commit and git push)
printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"The brain guards cannot run: no Python that imports brain (a missing or broken <BRAIN_HOME>/venv). Until it is fixed, the public and secrets checks refuse every git commit and git push. Fix: brain update, or rerun the installer (install.ps1 -Apply)."}}\n' "${1:-SessionStart}"
exit 0
