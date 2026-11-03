#!/usr/bin/env bash
# Run the PreToolUse guards (hooks/guard.py, brain/guards.py) on the hook's JSON on stdin; $1 is shell (Bash,
# PowerShell) or edit (Edit, Write, MultiEdit, NotebookEdit). A refusal is one JSON line on stdout; nothing else is
# printed. Uses $BRAIN_PYTHON, else the brain command's venv (<BRAIN_HOME>/venv: the installed engine), else python3,
# else python, skipping the Windows Store stubs. Without a Python 3, or on any error, the call goes through: it always
# exits 0, so a guard never breaks a session.

# needs_python KIND JSON: whether the guards have anything to read. A shell command that names neither git nor gh, nor
# anything that writes a file, nor a program of the owner and power guards, has not: no Python started. Writing is a >
# that is not a descriptor copy (2>&1, >&2) or a discard (>/dev/null, >$null), sed with -i or --in-place, or a name of
# brain/guards.py's tables (programs and cmdlets that write, interpreters, shells), looked for in the command only (its
# JSON string, escapes and all), not in the tool name or the description. tests/test_guards.py sources this file to
# check it against the tables, and against the programs of permissions.yaml's deny rules; the node lifecycle CLIs of
# config.json's power.node_clis come from <BRAIN_HOME>/cache/node-clis.txt, which brain/guards.py (node_tools) keeps
# as an alternation, since this hook cannot find config.json (the plugin runs from a cached copy): none until the
# first Python run writes it.
needs_python() {
  [ "$1" = "shell" ] || return 0
  case "$2" in *git*|*'gh '*) return 0 ;; esac
  local command='"command"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)"' text=$2 redirect discard found
  [[ $2 =~ $command ]] && text=${BASH_REMATCH[1]}
  redirect=${text//[0-9*]>&[0-9]/}
  redirect=${redirect//>&[0-9]/}
  for discard in '/dev/null' ' /dev/null' '$null' ' $null'; do redirect=${redirect//">$discard"/}; done
  case "$redirect" in *'>'*) return 0 ;; esac
  local before='(^|[^A-Za-z0-9_.-]|\\[nrt])'
  local writers="$before"'(rm|rmdir|unlink|shred|tee|touch|mkdir|truncate|mv|cp|ln|install|rsync|scp|chmod|chown|chgrp|sort|curl|perl|ruby|awk|gawk|dd|tar|bsdtar|unzip|patch|wget|find|xargs|py|node|bash|sh|zsh|dash|ksh|pwsh|powershell|cmd|iex|invoke-expression|set-content|add-content|clear-content|out-file|tee-object|export-csv|export-clixml|new-item|remove-item|rename-item|copy-item|move-item|start-transcript|expand-archive|compress-archive|invoke-webrequest|invoke-restmethod|sc|ac|clc|epcsv|ni|md|ri|rd|del|erase|rni|ren|cpi|copy|mi|move|iwr|irm|rename|mklink|xcopy|robocopy)([^A-Za-z0-9_-]|$)|python|\[(system\.)?io\.|'"$before"'sed[^|;&]*[[:space:]]-(-in-place|[A-Za-z]*i)'
  # The owner and power guards' programs (brain/guards.py: _owner_command, _power_command and their tables), the
  # --arm flag, brain usage allow (_usage_override), the override's name and a magic packet's 0xFF.
  local owner_power="$before"'(schtasks|register-scheduledtask|set-scheduledtask|unregister-scheduledtask|enable-scheduledtask|disable-scheduledtask|register-scheduledjob|set-scheduledjob|unregister-scheduledjob|new-service|set-service|remove-service|nssm|crontab|at|batch|atrm|systemctl|systemd-run|launchctl|reg|new-itemproperty|set-itemproperty|sp|install\.ps1|ssh-keygen|age-keygen|gpg2?|cmdkey|set-secret|remove-secret|register-secretvault|unregister-secretvault|set-secretstorepassword|reset-secretstore|new-storedcredential|remove-storedcredential|security|secret-tool|docker|npm|pnpm|yarn|az|gcloud|aws|argocd|net|new-localuser|set-localuser|remove-localuser|rename-localuser|enable-localuser|disable-localuser|add-localgroupmember|remove-localgroupmember|useradd|usermod|userdel|passwd|chpasswd|chage|groupadd|groupmod|groupdel|gpasswd|setx|k3s|microk8s|kubectl|kubecolor|oc|helm|https?|xh|shutdown|poweroff|reboot|halt|psshutdown|rtcwake|logoff|pm-suspend|pm-hibernate|pm-suspend-hybrid|stop-computer|restart-computer|init|telinit|loginctl|pmset|osascript|dbus-send|busctl|gdbus|rundll32|nircmd|wmic|invoke-cimmethod|invoke-wmimethod|bcdedit|efibootmgr|ipmitool|racadm|k3s-killall\.sh|k3s-uninstall\.sh|k3s-agent-uninstall\.sh|wakeonlan|wol|etherwake|ether-wake|wakemeonlan|mc-wol|wolcmd|send-wol|invoke-wakeonlan|send-wakeonlan|sigma_node_power|forge_boot|pxe_router|telegram-send|tg|telegram|power|ssh|plink|start-process|saps|start|brain_guard_allow|0xff|gh|git|255)([^A-Za-z0-9_-]|$)|--arm([^A-Za-z0-9_-]|$)|usage[[:space:]]+allow([^A-Za-z0-9_-]|$)|win32shutdown|setsuspendstate|exitwindowsex|initiatesystemshutdown|win32_operatingsystem'
  local clis='' cache="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}/cache/node-clis.txt"
  [ -f "$cache" ] && IFS= read -r clis < "$cache"
  local node_clis="$before($clis)([^A-Za-z0-9_-]|$)"
  shopt -s nocasematch
  [[ $text =~ $writers || $text =~ $owner_power || ( -n $clis && $text =~ $node_clis ) ]] && found=0 || found=1
  shopt -u nocasematch
  return $found
}

[ "${BASH_SOURCE[0]}" = "$0" ] || return 0
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
input=$(cat)
needs_python "${1:-}" "$input" || exit 0

home="${BRAIN_HOME:-$HOME/.brain}"
for py in "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python; do
  [ -n "$py" ] || continue
  path=$(command -v "$py" 2>/dev/null) || continue
  case "$path" in *WindowsApps*) continue ;; esac
  printf '%s' "$input" | "$path" -I "$root/hooks/guard.py" 2>/dev/null
  exit 0
done
exit 0
