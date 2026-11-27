#!/usr/bin/env bash
# PostToolUse: the budget watch (hooks/budget.py, brain.budget): at 80 % and at 100 % of the brief's context budget
# or of the recorded estimate of the items the brief names, one notice each as hook context; it never blocks.
# Fast path in bash builtins (no process started): Python sets the mtime of <BRAIN_HOME>/budget/<session>.mark in the
# future, when the next check is due; while the mark is newer than the transcript its line 1 names, it stops.
# Uses $BRAIN_PYTHON, else the brain command's venv (<BRAIN_HOME>/venv: the installed engine), else python3, else
# python, skipping the Windows Store stubs; without a Python 3 it does nothing.
# BRAIN_BUDGET_WATCH=0 turns it off.
# Before it, once per session, the rules injection's trace (wi-brain-hook-timeout-trace): at the session's first tool
# call, a start that left no <BRAIN_HOME>/session-rules/<session>.ok (inject-rules.sh writes it once the rules are
# out) is said to the session in one line of hook context: inject-rules was killed by its timeout, or failed, and the
# owner's rules may be missing. <session>.seen marks the check done: one test of a file per later call. Checked only
# where the folder exists (a machine whose inject-rules writes the mark). Not seen: a subagent's start (its calls carry
# its parent's session id) and a re-injection after a compaction (the session was checked at its first call).
watch=${BRAIN_BUDGET_WATCH:-1}
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || { selftime_bash() { :; }; brain_python() { return 1; }; }; } 2>/dev/null  # brain_t0, selftime_bash, brain_python
IFS= read -r -d '' payload
re_sid='"session_id"[[:space:]]*:[[:space:]]*"([A-Za-z0-9._-]+)"'
sid=
[[ $payload =~ $re_sid ]] && sid=${BASH_REMATCH[1]}
[[ -z $sid ]] && { selftime_bash "hook budget [bash]"; exit 0; }
rules_dir="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}/session-rules"
if [[ -d $rules_dir && ! -f $rules_dir/$sid.seen ]]; then
  { : > "$rules_dir/$sid.seen"; } 2>/dev/null
  if [[ ! -f $rules_dir/$sid.ok ]]; then
    root="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/..}"
    root=${root//\\/\\\\}
    printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"%s"}}\n' "No trace that this session's start injected the owner's rules: the inject-rules hook was killed by its timeout or failed. If the owner's rules are not in your context, read them now (the files config.json's rules names, else ${root//\"/\\\"}/rules/global.md) and follow them."
    selftime_bash "hook budget [bash]"
    exit 0
  fi
fi
[ "$watch" = "0" ] && exit 0
mark="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}/budget/$sid.mark"
if [[ -f $mark ]]; then
  # line 1 the transcript, line 2 the mark's format (brain.budget.MARK_FORMAT; none before 0.3.2): another starts Python
  watched= form=
  { IFS= read -r watched; IFS= read -r form; } < "$mark"
  [[ -n $watched && ( -z $form || $form == '#brain.budget-mark/v1' ) && $mark -nt $watched ]] && {
    selftime_bash "hook budget [bash]"; exit 0; }
fi

root="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/..}"
home="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}"
brain_python "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python && BRAIN_HOOK_T0=$brain_t0 "$brain_py" -X utf8 -I "$root/hooks/budget.py" PostToolUse <<<"$payload" 2>/dev/null
exit 0
