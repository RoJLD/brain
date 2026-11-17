#!/usr/bin/env bash
# PreToolUse (Bash, PowerShell): the background waiter's hint (hooks/waithint.py, brain.waithint;
# wi-brain-stuck-waiters, lesson les-brain-unbounded-background-waiter). A background call whose until or while loop has no deadline, no
# process check and no check that its file is still there gets one line of hook context: bound it, and stop the
# session's background tasks before deleting their logs or venvs. Never a refusal: it prints no permission decision,
# and exits 0 whatever happens.
# Fast path in bash builtins (no process started): a call whose JSON is not run in the background, or names no until
# or while (at a line's start too: JSON spells a newline \n), stops here. Before that, Claude Code starts it only on a
# likely hit: an if condition is matched against each simple command of the call, not the loop's keyword, so
# hooks.json gates it on what a wait loop's body runs, a sleep (Bash(*sleep*), PowerShell(*leep*): Start-Sleep and
# sleep); a busy loop with no sleep is not seen.
# Uses $BRAIN_PYTHON, else the brain command's venv (<BRAIN_HOME>/venv: the installed engine), else python3, else
# python, skipping the Windows Store stubs; without a Python 3 it does nothing. BRAIN_WAIT_HINT=0 turns it off.
[ "${BRAIN_WAIT_HINT:-1}" = "0" ] && exit 0
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || { selftime_bash() { :; }; brain_python() { return 1; }; }; } 2>/dev/null  # brain_t0, selftime_bash, brain_python
IFS= read -r -d '' payload
background='"run_in_background"[[:space:]]*:[[:space:]]*true'
loop='([^A-Za-z0-9_-]|\\[nrt])(until|while|Until|While|UNTIL|WHILE)[^A-Za-z0-9_-]'
[[ $payload =~ $background && $payload =~ $loop ]] || { selftime_bash "hook waithint [bash]"; exit 0; }

root="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/..}"
home="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}"
brain_python "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python && BRAIN_HOOK_T0=$brain_t0 "$brain_py" -X utf8 -I "$root/hooks/waithint.py" PreToolUse <<<"$payload" 2>/dev/null
exit 0
