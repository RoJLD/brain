#!/usr/bin/env bash
# Print the owner's rules as hook context for the event named in $1 (SessionStart or SubagentStart): the files of
# config.json's "rules" (relative to its folder), else the plugin's rules/global.md. config.json is $BRAIN_CONFIG, else
# $CLAUDE_BRAIN_DIR/config.json, else the one of the repo that holds the plugin (plugins/<plugin>/ -> its root); a
# cached copy of the plugin has none, and injects its own rules/global.md.
# JSON is read and built with bash, tr, sed and awk only, so the hook needs nothing beyond bash (Git Bash on Windows).
set -euo pipefail

event="${1:-SessionStart}"
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

config="${BRAIN_CONFIG:-}"
if [ -z "$config" ] && [ -n "${CLAUDE_BRAIN_DIR:-}" ] && [ -f "$CLAUDE_BRAIN_DIR/config.json" ]; then
  config="$CLAUDE_BRAIN_DIR/config.json"
fi
[ -n "$config" ] || config="$root/../../config.json"

rules=()
if [ -f "$config" ]; then
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
