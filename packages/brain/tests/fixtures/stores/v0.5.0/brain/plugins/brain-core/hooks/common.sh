# What the hooks share in bash, sourced by each one on its first line; builtins only, no fork.
#
# The self-timing (brain/selftime.py, wi-brain-self-timing): brain_t0 is the hook's start; a hook that runs Python
# passes it as BRAIN_HOOK_T0, so its one exec event, written by Python, counts the interpreter's start; a hook that
# ends in bash calls selftime_bash TASK, which appends the event to <BRAIN_HOME>/ledger/engine/exec-bash-<yyyy-mm>.jsonl:
# one printf >> per event, which bash opens O_APPEND (whole lines with several writers at once, on Windows too).
# BRAIN_SELFTIME=0 turns it off; it never fails the hook. brain_version is the engine's (tests/test_selftime.py checks
# it against brain.__version__).
#
# The hook contract (wi-brain-hook-contracts, docs/formats.md « The hook contract »): BRAIN_HOOK_VERSION, exported,
# gives the Python a hook starts this file's brain_version, so the SessionStart health reports a plugin copy older or
# newer than the engine it runs on. Every hook spells <BRAIN_HOME> as ${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}, the
# folder Python's Path.home() names on Windows.

brain_t0=$EPOCHREALTIME
brain_version=0.5.0
export BRAIN_HOOK_VERSION=$brain_version

# selftime_bash TASK [EXIT]: the exec event of this hook's bash run (project brain, the task, the engine's version).
selftime_bash() {
  [ "${BRAIN_SELFTIME:-1}" = "0" ] && return 0
  [ -n "$brain_t0" ] || return 0
  local t1=$EPOCHREALTIME us0 us1 d at0 at1 dir task=${1//[\"\\]/}
  us0=${brain_t0//[.,]/} us1=${t1//[.,]/}
  d=$((10#$us1 - 10#$us0))
  [ "$d" -ge 0 ] || d=0
  TZ=UTC0 printf -v at0 '%(%Y-%m-%dT%H:%M:%S)T.%03dZ' "${brain_t0%[.,]*}" $(((10#${brain_t0#*[.,]}) / 1000))
  TZ=UTC0 printf -v at1 '%(%Y-%m-%dT%H:%M:%S)T.%03dZ' "${t1%[.,]*}" $(((10#${t1#*[.,]}) / 1000))
  dir="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}/ledger/engine"
  [ -d "$dir" ] || mkdir -p "$dir" 2>/dev/null || return 0
  printf '{"v":1,"kind":"exec","at":"%s","host":"%s","project":"brain","task":"%s","version":"%s","start":"%s","end":"%s","duration_s":%d.%03d,"exit":%d,"pid":%d}\n' \
    "$at1" "${BRAIN_HOST:-${HOSTNAME:-unknown}}" "$task" "$brain_version" "$at0" "$at1" $((d / 1000000)) \
    $((d % 1000000 / 1000)) "${2:-0}" "$$" >> "$dir/exec-bash-${at1:0:7}.jsonl" 2>/dev/null
  return 0
}

# brain_python CANDIDATE...: sets brain_py to the first candidate that is a Python, without a fork (was $(command -v),
# ~55 ms on Windows): a path is tested with -x, a bare name looked up in PATH by hash; the Windows Store stubs
# (WindowsApps) are skipped. Returns 1 when none is.
brain_python() {
  local py
  for py in "$@"; do
    [ -n "$py" ] || continue
    if [[ $py == */* || $py == *'\'* ]]; then
      [ -x "$py" ] || continue
    else
      hash "$py" 2>/dev/null || continue
      py=${BASH_CMDS[$py]}
      [ -n "$py" ] || continue
    fi
    case $py in *WindowsApps*) continue ;; esac
    brain_py=$py
    return 0
  done
  return 1
}
