#!/usr/bin/env bash
# Print the owner's rules as hook context for the event named in $1 (SessionStart or SubagentStart): the files of
# config.json's "rules" (relative to its folder), else the plugin's rules/global.md. config.json is $BRAIN_CONFIG, else
# the first found in $CLAUDE_BRAIN_DIR, $BRAIN_PERSONAL, the repo that holds the plugin (plugins/<plugin>/ -> its root)
# and the personal brain the installer's pointer names (<BRAIN_HOME>/personal.json, {"root": ...}); without one (a
# cached copy of the plugin on a machine with no pointer) it injects the plugin's own rules/global.md.
# JSON is read and built with bash, tr, sed and awk only, so the hook needs nothing beyond bash (Git Bash on Windows).
set -euo pipefail
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || { selftime_bash() { :; }; brain_python() { return 1; }; }; } 2>/dev/null  # brain_t0, selftime_bash, brain_python

event="${1:-SessionStart}"
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

config="${BRAIN_CONFIG:-}"
if [ -z "$config" ]; then
  pointer="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}/personal.json" personal=
  if [ -f "$pointer" ]; then
    json=$(tr -d '\r\n' < "$pointer")
    key='"root"[[:space:]]*:[[:space:]]*"([^"]+)"'
    # a JSON-escaped backslash (\\) becomes a slash: E:\\work\\me -> E:/work/me
    [[ $json =~ $key ]] && personal=${BASH_REMATCH[1]//\\\\//}
  fi
  for base in "${CLAUDE_BRAIN_DIR:-}" "${BRAIN_PERSONAL:-}" "$root/../.." "$personal"; do
    if [ -n "$base" ] && [ -f "$base/config.json" ]; then config="$base/config.json"; break; fi
  done
fi

rules=()
# The hook contract brain sync renders beside this script (hooks/contract.txt, brain.render.hook_contract): its "rule"
# lines are config.json's "rules", read without parsing JSON. It is read only for the config the plugin was rendered
# from as it was then: no BRAIN_CONFIG or CLAUDE_BRAIN_DIR naming another, and a contract newer than config.json (a
# rules edit since the render is read from config.json at once). Otherwise, with another format, or with no contract
# (the engine's own copy, a plugin rendered before 0.3.2), the first "rules" array of config.json.
contract="$root/hooks/contract.txt" form=
if [ -f "$contract" ]; then IFS= read -r form < "$contract" || :; fi
form=${form%$'\r'}
if [ -f "$config" ] && [ "$form" = "#brain.hook-contract/v1" ] && [ -z "${BRAIN_CONFIG:-}${CLAUDE_BRAIN_DIR:-}" ] \
   && [ "$contract" -nt "$config" ]; then
  base=$(cd "$(dirname "$config")" && pwd)
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    case $line in 'rule '?*) [ -f "$base/${line#rule }" ] && rules+=("$base/${line#rule }") ;; esac
  done < "$contract"
elif [ -f "$config" ]; then
  base=$(cd "$(dirname "$config")" && pwd)
  json=$(tr -d '\r\n' < "$config")
  list='"rules"[[:space:]]*:[[:space:]]*\[([^]]*)\]'
  if [[ $json =~ $list ]]; then
    items=${BASH_REMATCH[1]}
    item='^[^"]*"([^"]+)"(.*)$'
    while [[ $items =~ $item ]]; do
      [ -f "$base/${BASH_REMATCH[1]}" ] && rules+=("$base/${BASH_REMATCH[1]}")
      items=${BASH_REMATCH[2]}
    done
  fi
fi
[ ${#rules[@]} -gt 0 ] || rules=("$root/rules/global.md")

# JSON string: drop CR (CRLF checkouts), tabs to spaces, escape backslashes and quotes, newlines to \n; a blank line
# between two files.
text() {
  local i
  for i in "${!rules[@]}"; do
    [ "$i" -eq 0 ] || printf '\n'
    tr -d '\r' < "${rules[$i]}" | tr '\t' ' '
  done
}
context=$(text | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | awk '{printf "%s\\n", $0}')

printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"%s"}}\n' "$event" "$context"
selftime_bash "hook inject-rules $event [bash]"
