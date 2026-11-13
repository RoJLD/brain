#!/usr/bin/env bash
# UserPromptSubmit: announce the decisions answered or newly asked in the project's queue (records/ddr of its main
# checkout) since the session started or since the last announce (hooks/midsession.py, brain.midsession), as hook
# context; prints nothing when none was.
# Fast path in bash builtins (no process started): when the session's folder is the one in its mark
# (<BRAIN_HOME>/announce/<session>.mark: the folder, the queue, the pending DDRs) and neither the queue folder (a DDR
# added or removed) nor a pending DDR (an answer) is newer than the mark, it stops.
# Uses $BRAIN_PYTHON, else the brain command's venv (<BRAIN_HOME>/venv: the installed engine), else python3, else
# python, skipping the Windows Store stubs; without a Python 3 it does nothing.
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || { selftime_bash() { :; }; brain_python() { return 1; }; }; } 2>/dev/null  # brain_t0, selftime_bash, brain_python
IFS= read -r -d '' payload
re_sid='"session_id"[[:space:]]*:[[:space:]]*"([A-Za-z0-9._-]+)"'
re_cwd='"cwd"[[:space:]]*:[[:space:]]*"([^"\\]*(\\.[^"\\]*)*)"'
sid= cwd=
[[ $payload =~ $re_sid ]] && sid=${BASH_REMATCH[1]}
[[ $payload =~ $re_cwd ]] && cwd=${BASH_REMATCH[1]}
mark="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}/announce/$sid.mark"
if [[ -n $sid && -f $mark ]]; then
  newer=1
  {
    IFS= read -r marked_cwd
    IFS= read -r queue
    if [[ $marked_cwd == "$cwd" ]]; then
      newer=
      [[ -n $queue && $queue -nt $mark ]] && newer=1
      # the last line is the mark's format (brain.midsession.MARK_FORMAT; none before 0.3.2), read with or without a
      # queue: another format starts Python
      while [[ -z $newer ]] && IFS= read -r name; do
        if [[ $name == '#'* ]]; then [[ $name == '#brain.announce-mark/v1' ]] || newer=1
        elif [[ -n $queue && -n $name && $queue/$name -nt $mark ]]; then newer=1
        fi
      done
    fi
  } < "$mark"
  [[ -z $newer ]] && { selftime_bash "hook midsession [bash]"; exit 0; }
fi

root="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/..}"
home="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}"
brain_python "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python && BRAIN_HOOK_T0=$brain_t0 "$brain_py" -X utf8 -I "$root/hooks/midsession.py" UserPromptSubmit <<<"$payload" 2>/dev/null
exit 0
