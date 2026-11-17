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
brain_version=0.5.1
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
# (WindowsApps) are skipped, and so is a candidate whose file name holds no python (nor is py or pypy*): a
# BRAIN_PYTHON set to true.exe would make every guard pass (wi-brain-unadopted-floor). Returns 1 when none is.
brain_python() {
  local py base locked="${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/locked-python"
  # The locked guard's copy (brain floor lock) names its own interpreter beside this file: its hooks run the copy's
  # engine, never one the environment or the user's venv picks.
  if [ -f "$locked" ] && IFS= read -r py < "$locked" && [ -x "${py%$'\r'}" ]; then brain_py=${py%$'\r'}; return 0; fi
  for py in "$@"; do
    [ -n "$py" ] || continue
    base=${py##*/}; base=${base##*\\}
    case $base in *[Pp][Yy][Tt][Hh][Oo][Nn]*|[Pp][Yy]|[Pp][Yy].[Ee][Xx][Ee]|[Pp][Yy][Pp][Yy]*) ;; *) continue ;; esac
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

# brain_config PLUGIN_ROOT: prints the config.json the engine reads, found as inject-rules.sh finds it: $BRAIN_CONFIG,
# else the first found in $CLAUDE_BRAIN_DIR, $BRAIN_PERSONAL, the repo that holds the plugin and the personal brain
# the pointer <BRAIN_HOME>/personal.json names; nothing when there is none.
brain_config() {
  if [ -n "${BRAIN_CONFIG:-}" ]; then printf '%s\n' "$BRAIN_CONFIG"; return 0; fi
  local pointer="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}/personal.json" personal= json key base
  if [ -f "$pointer" ]; then
    json=$(tr -d '\r\n' < "$pointer")
    key='"root"[[:space:]]*:[[:space:]]*"([^"]+)"'
    [[ $json =~ $key ]] && personal=${BASH_REMATCH[1]//\\\\//}
  fi
  for base in "${CLAUDE_BRAIN_DIR:-}" "${BRAIN_PERSONAL:-}" "$1/../.." "$personal"; do
    if [ -n "$base" ] && [ -f "$base/config.json" ]; then printf '%s\n' "$base/config.json"; return 0; fi
  done
}

# floor_setting CONFIG KEY [SECTION]: prints 1 when config.json's top-level "floor" object (or SECTION's: guards, for
# guards.refuse_token_read) holds "KEY": true (brain/floor.py's settings: a "floor" nested in another object is not
# the setting, the last of two keys of one name wins). awk walks the JSON's strings and depth.
floor_setting() {
  [ -f "$1" ] || return 0
  LC_ALL=C awk -v want="$2" -v sec="${3:-floor}" 'BEGIN { RS = "\001" } {
    s = $0; n = length(s); d = 0; str = 0; esc = 0; tok = ""; key = ""; fd = 0; on = 0
    for (i = 1; i <= n; i++) {
      c = substr(s, i, 1)
      if (str) { if (esc) esc = 0; else if (c == "\\") esc = 1; else if (c == "\"") str = 0; else tok = tok c; continue }
      if (c == "\"") { str = 1; tok = ""; continue }
      if (c == ":") {
        key = tok
        if (d == 1 && key == sec) on = 0
        if (fd && d == 2 && key == want) { v = substr(s, i + 1); sub(/^[ \t\r\n]+/, "", v); on = (v ~ /^true([^A-Za-z0-9_]|$)/) }
      } else if (c == "{" || c == "[") { fd = fd || (d == 1 && c == "{" && key == sec); d++; key = "" }
      else if (c == "}" || c == "]") { d--; if (d <= 1) fd = 0; key = "" }
      else if (c == ",") key = ""
    }
    if (on) print 1 }' "$1" 2>/dev/null || :
}
