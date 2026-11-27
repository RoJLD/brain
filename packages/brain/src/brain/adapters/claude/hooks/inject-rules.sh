#!/usr/bin/env bash
# Print the owner's rules as hook context for the event named in $1 (SessionStart or SubagentStart): the files of
# config.json's "rules" (relative to its folder), else the plugin's rules/global.md. config.json is $BRAIN_CONFIG, else
# the first found in $CLAUDE_BRAIN_DIR, $BRAIN_PERSONAL, the repo that holds the plugin (plugins/<plugin>/ -> its root)
# and the personal brain the installer's pointer names (<BRAIN_HOME>/personal.json, {"root": ...}); without one (a
# cached copy of the plugin on a machine with no pointer) it injects the plugin's own rules/global.md.
# JSON is read and built with bash builtins alone, so the hook needs nothing beyond bash (Git Bash on Windows) and
# starts no process (wi-brain-hook-timeout-trace): each tr, sed, awk, dirname or $(...) cost 35 to 90 ms on Windows
# at rest and up to seconds under load (10.5 s against the 10 s timeout on 2026-11-27: that session started without
# the rules). The one awk left reads a "floor" section, started only when config.json names both "floor" and "only".
# A run that printed the rules leaves <BRAIN_HOME>/session-rules/<session_id>.ok, the id read from the event's JSON on
# stdin: the budget watch (budget.sh) says at the session's first tool call when its start left none.
set -euo pipefail
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || { selftime_bash() { :; }; floor_setting() { :; }; }; } 2>/dev/null  # brain_t0, selftime_bash, floor_setting

event="${1:-SessionStart}"
root="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/..}"
home="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}"

# slurp FILE: the file's whole text into $slurped, its NUL bytes dropped as $(...) dropped them (a UTF-16 file);
# read -d '' stops at each NUL and at the end, where its status 1 is no failure. A file it cannot open leaves ''.
slurp() {
  local part=
  slurped=
  { while IFS= read -r -d '' part; do slurped+=$part; done; slurped+=$part; } < "$1" 2>/dev/null || :
}
# folder_of PATH: the folder of a file's path into $folder, / or \ separated, '.' for a bare name.
folder_of() { folder=${1%[/\\]*}; [ "$folder" != "$1" ] || folder=.; }

config="${BRAIN_CONFIG:-}"
if [ -z "$config" ]; then
  pointer="$home/personal.json" personal=
  if [ -f "$pointer" ]; then
    slurp "$pointer"
    json=${slurped//[$'\r\n']/}
    key='"root"[[:space:]]*:[[:space:]]*"([^"]+)"'
    # a JSON-escaped backslash (\\) becomes a slash: E:\\work\\me -> E:/work/me
    [[ $json =~ $key ]] && personal=${BASH_REMATCH[1]//\\\\//}
  fi
  for base in "${CLAUDE_BRAIN_DIR:-}" "${BRAIN_PERSONAL:-}" "$root/../.." "$personal"; do
    if [ -n "$base" ] && [ -f "$base/config.json" ]; then config="$base/config.json"; break; fi
  done
fi

rules=() json=
if [ -f "$config" ]; then slurp "$config"; json=${slurped//[$'\r\n']/}; fi
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
  folder_of "$config"
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    case $line in 'rule '?*) [ -f "$folder/${line#rule }" ] && rules+=("$folder/${line#rule }") ;; esac
  done < "$contract"
elif [ -f "$config" ]; then
  folder_of "$config"
  list='"rules"[[:space:]]*:[[:space:]]*\[([^]]*)\]'
  if [[ $json =~ $list ]]; then
    items=${BASH_REMATCH[1]}
    item='^[^"]*"([^"]+)"(.*)$'
    while [[ $items =~ $item ]]; do
      [ -f "$folder/${BASH_REMATCH[1]}" ] && rules+=("$folder/${BASH_REMATCH[1]}")
      items=${BASH_REMATCH[2]}
    done
  fi
fi
[ ${#rules[@]} -gt 0 ] || rules=("$root/rules/global.md")

# The rules' text: CR dropped (CRLF checkouts), tabs made spaces, a blank line between two files.
text=
for i in "${!rules[@]}"; do
  [ "$i" -eq 0 ] || text+=$'\n'
  slurp "${rules[$i]}"
  text+=$slurped
done
text=${text//$'\r'/}
text=${text//$'\t'/ }
# A floor-only machine (config.json "floor": {"only": true} at its top level, brain/floor.py) gets the locked rules
# alone: the lines that carry <!-- lock --> or <!-- lock: ID -->, every marker and the trailing blanks taken out, after
# brain.floor.ONLY_LINE (the same words: tests/test_floor.py compares them). common.sh's floor_setting reads the
# top-level "floor" as Python's json does. The locked lines are read in the C locale, so [[:space:]] and [A-Za-z] mean
# what brain.floor.LOCK means.
floor_only=
if [[ $json == *'"floor"'* && $json == *'"only"'* ]]; then floor_only=$(floor_setting "$config" only); fi
if [ -n "$floor_only" ]; then
  LC_ALL=C
  lock='[[:space:]]*<!--[[:space:]]*lock(:[[:space:]]*[A-Za-z0-9_.-]+)?[[:space:]]*-->'
  kept="Floor only (config.json floor.only): this machine gets the locked rules alone, until it is adopted; the guard applies only the floor's refusals, the secrets and configuration checks, the override protection and the session-settings and scheduled-task checks, and the memory notes are not synced."$'\n'
  while IFS= read -r line; do
    [[ $line =~ $lock ]] || continue
    while [[ $line =~ $lock ]]; do line=${line/"${BASH_REMATCH[0]}"/}; done
    line=${line%"${line##*[![:space:]]}"}
    kept+=$line$'\n'
  done <<< "$text"
  text=$kept
fi
# JSON string: backslashes and quotes escaped, newlines as \n, the last line ended.
if [ -n "$text" ] && [ "${text: -1}" != $'\n' ]; then text+=$'\n'; fi
text=${text//\\/\\\\}
text=${text//\"/\\\"}
text=${text//$'\n'/\\n}

printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"%s"}}\n' "$event" "$text"
# The session's mark: its id from the event's JSON, read from a pipe or a file (never a terminal), 2 s at most; none
# when no rule was read (no rules file: budget.sh then says the rules are missing).
if [ -n "$text" ] && [ ! -t 0 ]; then
  payload=
  IFS= read -r -d '' -t 2 payload || :
  re_sid='"session_id"[[:space:]]*:[[:space:]]*"([A-Za-z0-9._-]+)"'
  if [[ $payload =~ $re_sid ]]; then
    { [ -d "$home/session-rules" ] || mkdir -p "$home/session-rules"; } 2>/dev/null \
      && { : > "$home/session-rules/${BASH_REMATCH[1]}.ok"; } 2>/dev/null || :
  fi
fi
selftime_bash "hook inject-rules $event [bash]"
