#!/usr/bin/env bash
# PreToolUse (Read, Grep): the owner guard's check token (brain/tokenguard.py, wi-brain-ipc-token-read-guard): a Read
# or a Grep that reaches the machine's IPC token file (<BRAIN_HOME>/ipc/token, or $BRAIN_IPC_TOKEN_FILE) is refused,
# one JSON line on stdout, as guard.sh prints it (hooks/guard.py read). Shell calls and edits are guard.sh's.
# Opt-in: brain render --target claude (brain sync) registers it in hooks.json only when config.json
# guards.refuse_token_read is true (brain.render.OPTIONAL_HOOKS); off, no Read or Grep pays its cost. A locked floor's
# managed hooks leave it out (brain.floorlock: its PreToolUse hooks are floorhook.HOOKS).
# Fast path in bash builtins: a call whose JSON names neither ipc, nor token, nor the brain's home (.brain, or
# BRAIN_HOME's folder), nor the file BRAIN_IPC_TOKEN_FILE names, and whose path is no link (a trailing separator
# dropped, a relative path read from the call's cwd), starts no Python. It always exits 0: an error lets the call
# through (the check is advisory: docs/guards.md, « The machine's token »).
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || { selftime_bash() { :; }; brain_python() { return 1; }; }; } 2>/dev/null  # brain_t0, selftime_bash, brain_python

# reads_token JSON: whether the Read or Grep call may reach the token (0) or surely not (1).
reads_token() {
  local path='"(file_path|path)"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)"' cwd='"cwd"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)"'
  local home=${BRAIN_HOME:-} tok=${BRAIN_IPC_TOKEN_FILE:-} p d
  home=${home%[\\/]}; home=${home##*[\\/]}; tok=${tok%[\\/]}; tok=${tok##*[\\/]}
  shopt -s nocasematch
  case "$1" in *ipc*|*token*|*.brain*) shopt -u nocasematch; return 0 ;; esac
  if [[ -n $home && $1 =~ [\\/]"$home"([\\/\"]|$) ]] || [[ -n $tok && $1 == *"$tok"* ]]; then
    shopt -u nocasematch; return 0
  fi
  shopt -u nocasematch
  if [[ $1 =~ $path ]]; then
    p=${BASH_REMATCH[2]//\\\\/\\}
    p=${p%[\\/]}
    if [[ $p != [\\/]* && $p != [A-Za-z]:* && $1 =~ $cwd ]]; then
      d=${BASH_REMATCH[1]//\\\\/\\}
      p="$d/$p"
    fi
    [ -L "$p" ] && return 0
  fi
  return 1
}

[ "${BASH_SOURCE[0]}" = "$0" ] || return 0
root="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/..}"
IFS= read -r -d '' input  # the hook's JSON, without $(cat)'s fork
reads_token "$input" || { selftime_bash "hook tokenguard [bash]"; exit 0; }
home="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}"
brain_python "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python && BRAIN_HOOK_T0=$brain_t0 "$brain_py" -X utf8 -I "$root/hooks/guard.py" read <<<"$input" 2>/dev/null
exit 0
