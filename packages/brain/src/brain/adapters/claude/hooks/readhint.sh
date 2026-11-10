#!/usr/bin/env bash
# PreToolUse (Read, Grep, Bash, PowerShell): the read commands' hint (hooks/readhint.py, brain.readhint). When a call
# reads a registered brain's graph YAML, decision log, journal or generated views by hand, one line of hook context
# names the brain command that answers (brain item show, brain items, brain adr show, brain journal last...). Never a
# refusal: it prints no permission decision, and exits 0 whatever happens.
# Fast path in bash builtins (no process started): a call whose JSON names none of those files (a store's nodes/ or
# edges/ YAML, a folder named graph, decisions.md, journal.md, a *_graph.md view, decision_queue.md, FEATURES.md)
# stops here. It runs beside guard.sh on a shell call (Claude Code runs a tool's hooks in parallel).
# Uses $BRAIN_PYTHON, else the brain command's venv (<BRAIN_HOME>/venv: the installed engine), else python3, else
# python, skipping the Windows Store stubs; without a Python 3 it does nothing.
# Opt-in: brain render --target claude (brain sync) registers it in hooks.json only when config.json hints.read is
# true (brain.render.OPTIONAL_HOOKS); off, no call pays its cost. BRAIN_READ_HINT=0 turns it off while it is on.
[ "${BRAIN_READ_HINT:-1}" = "0" ] && exit 0
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || { selftime_bash() { :; }; brain_python() { return 1; }; }; } 2>/dev/null  # brain_t0, selftime_bash, brain_python
IFS= read -r -d '' payload
brain_files='(nodes|edges)[/\\]+[^"]*\.ya?ml|[/\\]graph[/\\]*"|decisions\.md|journal\.md|_graph\.md|decision_queue\.md|FEATURES\.md'
[[ $payload =~ $brain_files ]] || { selftime_bash "hook readhint [bash]"; exit 0; }

root="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/..}"
home="${BRAIN_HOME:-$HOME/.brain}"
brain_python "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python && BRAIN_HOOK_T0=$brain_t0 "$brain_py" -X utf8 -I "$root/hooks/readhint.py" PreToolUse <<<"$payload" 2>/dev/null
exit 0
