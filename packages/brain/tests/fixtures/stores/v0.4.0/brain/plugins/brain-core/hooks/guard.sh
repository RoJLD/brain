#!/usr/bin/env bash
# Run the PreToolUse guards (hooks/guard.py, brain/guards.py) on the hook's JSON on stdin; $1 is shell (Bash,
# PowerShell) or edit (Edit, Write, MultiEdit, NotebookEdit). A refusal is one JSON line on stdout; nothing else is
# printed. Uses $BRAIN_PYTHON, else the brain command's venv (<BRAIN_HOME>/venv: the installed engine), else python3,
# else python, skipping the Windows Store stubs. It always exits 0, so a guard never breaks a session: on an error the
# call goes through, except where a leak is possible (COMPAT-4, wi-brain-guards-fail-closed): when no Python is found,
# or the one found cannot run guard.py (it cannot import brain: a broken or missing venv), a shell command that names
# git and commit or push is refused (commits_or_pushes), the reason naming the fix (brain update, the installer).

# needs_python KIND JSON: whether the guards have anything to read. A shell command that names neither gh, nor git
# but to read (git [-C DIR | --no-pager | -P] SUB, SUB in brain/guards.py's GIT_READS, without --output or a pager
# option: tests/test_guards.py checks the list against the guards' tables), nor anything that writes a file, nor a
# program of the owner and power guards, has not: no Python started. Writing is a >
# that is not a descriptor copy (2>&1, >&2) or a discard (>/dev/null, >$null), sed with -i or --in-place, or a name of
# brain/guards.py's tables (programs and cmdlets that write, interpreters, shells), looked for in the command only (its
# JSON string, escapes and all), not in the tool name or the description. tests/test_guards.py sources this file to
# check it against the tables, and against the programs of permissions.yaml's deny rules; the node lifecycle CLIs of
# config.json's power.node_clis come from <BRAIN_HOME>/cache/node-clis.txt, which brain/guards.py (node_tools) keeps
# as an alternation, since this hook cannot find config.json (the plugin runs from a cached copy): none until the
# first Python run writes it.
{ . "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh" || { selftime_bash() { :; }; brain_python() { return 1; }; }; } 2>/dev/null  # brain_t0, selftime_bash, brain_python

needs_python() {
  [ "$1" = "shell" ] || return 0
  case "$2" in *'gh '*) return 0 ;; esac
  local command='"command"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)"' text=$2 redirect discard found
  [[ $2 =~ $command ]] && text=${BASH_REMATCH[1]}
  # git that only reads is taken out of the text; any other git (another subcommand, -c, --git-dir, an alias) stays
  local gitread='(^|[^A-Za-z0-9_.-]|\\[nrt])git(\.exe)?[[:space:]]+((-C[[:space:]]+[^[:space:];&|"]+|--no-pager|-P)[[:space:]]+)*(status|log|diff|show|rev-parse|ls-files|ls-tree|blame|describe|shortlog|rev-list|merge-base|cat-file|name-rev|grep|check-ignore|count-objects|var|version|whatchanged|show-ref|for-each-ref)([^A-Za-z0-9_-]|$)'
  local rest=$text reads=
  while [[ $rest =~ $gitread ]]; do
    rest=${rest/"${BASH_REMATCH[0]}"/"${BASH_REMATCH[1]} ${BASH_REMATCH[6]}"}
    reads=1
  done
  case "$rest" in *git*) return 0 ;; esac
  [[ -n $reads && $rest =~ --output|--open-files-in-pager|[[:space:]]-O ]] && return 0
  redirect=${text//[0-9*]>&[0-9]/}
  redirect=${redirect//>&[0-9]/}
  for discard in '/dev/null' ' /dev/null' '$null' ' $null'; do redirect=${redirect//">$discard"/}; done
  case "$redirect" in *'>'*) return 0 ;; esac
  local before='(^|[^A-Za-z0-9_.-]|\\[nrt])'
  local writers="$before"'(rm|rmdir|unlink|shred|tee|touch|mkdir|truncate|mv|cp|ln|install|rsync|scp|chmod|chown|chgrp|sort|curl|perl|ruby|awk|gawk|dd|tar|bsdtar|unzip|patch|wget|find|xargs|py|node|bash|sh|zsh|dash|ksh|pwsh|powershell|cmd|iex|invoke-expression|set-content|add-content|clear-content|out-file|tee-object|export-csv|export-clixml|new-item|remove-item|rename-item|copy-item|move-item|start-transcript|expand-archive|compress-archive|invoke-webrequest|invoke-restmethod|sc|ac|clc|epcsv|ni|md|ri|rd|del|erase|rni|ren|cpi|copy|mi|move|iwr|irm|rename|mklink|xcopy|robocopy)([^A-Za-z0-9_-]|$)|python|\[(system\.)?io\.|'"$before"'sed[^|;&]*[[:space:]]-(-in-place|[A-Za-z]*i)'
  # The owner and power guards' programs (brain/guards.py: _owner_command, _power_command and their tables), the
  # --arm flag, brain usage allow (_usage_override), brain handover (_root_override), the words ipc and otel-headers
  # (brain ipc otel-headers, whatever runs it, quoted or not), the override's name, a magic packet's 0xFF, and the
  # third-party guard's claude plugin and skills add (_kit_command; its downloaders and shells are in the lists
  # already): claude or skills, then plugin or add as a later word, whatever comes between (a quote after a quoted claude.exe, global
  # options such as --model opus, a line continuation).
  local owner_power="$before"'(schtasks|register-scheduledtask|set-scheduledtask|unregister-scheduledtask|enable-scheduledtask|disable-scheduledtask|register-scheduledjob|set-scheduledjob|unregister-scheduledjob|new-service|set-service|remove-service|nssm|crontab|at|batch|atrm|systemctl|systemd-run|launchctl|reg|new-itemproperty|set-itemproperty|sp|install\.ps1|ssh-keygen|age-keygen|gpg2?|cmdkey|set-secret|remove-secret|register-secretvault|unregister-secretvault|set-secretstorepassword|reset-secretstore|new-storedcredential|remove-storedcredential|security|secret-tool|docker|npm|pnpm|yarn|az|gcloud|aws|argocd|net|new-localuser|set-localuser|remove-localuser|rename-localuser|enable-localuser|disable-localuser|add-localgroupmember|remove-localgroupmember|useradd|usermod|userdel|passwd|chpasswd|chage|groupadd|groupmod|groupdel|gpasswd|setx|k3s|microk8s|kubectl|kubecolor|oc|helm|https?|xh|shutdown|poweroff|reboot|halt|psshutdown|rtcwake|logoff|pm-suspend|pm-hibernate|pm-suspend-hybrid|stop-computer|restart-computer|init|telinit|loginctl|pmset|osascript|dbus-send|busctl|gdbus|rundll32|nircmd|wmic|invoke-cimmethod|invoke-wmimethod|bcdedit|efibootmgr|ipmitool|racadm|k3s-killall\.sh|k3s-uninstall\.sh|k3s-agent-uninstall\.sh|wakeonlan|wol|etherwake|ether-wake|wakemeonlan|mc-wol|wolcmd|send-wol|invoke-wakeonlan|send-wakeonlan|sigma_node_power|forge_boot|pxe_router|telegram-send|tg|telegram|power|ssh|plink|start-process|saps|start|brain_guard_allow|ipc|otel-headers|0xff|gh|git|255)([^A-Za-z0-9_-]|$)|--arm([^A-Za-z0-9_-]|$)|usage[[:space:]]+allow([^A-Za-z0-9_-]|$)|handover([^A-Za-z0-9_-]|$)|schedule[[:space:]]+install([^A-Za-z0-9_-]|$)|win32shutdown|setsuspendstate|exitwindowsex|initiatesystemshutdown|win32_operatingsystem|'"$before"'(claude(\.exe)?|skills(@[^[:space:]]*)?)(([^A-Za-z0-9_-]|\\[nrt]).*)?([[:space:]]|\\[nrt])(plugins?|add)([^A-Za-z0-9_-]|$)'
  # node-clis.txt: line 1 the alternation, line 2 its format (brain.guards.NODE_CLI_FORMAT; none before 0.3.2): with
  # another format the pre-filter cannot read the CLIs, so the guards read the command
  local clis='' form='' cache="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}/cache/node-clis.txt"
  [ -f "$cache" ] && { IFS= read -r clis; IFS= read -r form; } < "$cache"
  [[ -n $form && $form != '#brain.node-clis/v1' ]] && return 0
  local node_clis="$before($clis)([^A-Za-z0-9_-]|$)"
  shopt -s nocasematch
  [[ $rest =~ $writers || $rest =~ $owner_power || ( -n $clis && $rest =~ $node_clis ) ]] && found=0 || found=1
  shopt -u nocasematch
  return $found
}

# commits_or_pushes KIND JSON: whether a shell command names git, then commit or push (any case, any path or quote
# around git, any option between): what the public and secrets checks judge, refused when they cannot run. Wider than
# the guards on purpose (git log --grep push is caught too): it only ever runs while the guards are broken.
commits_or_pushes() {
  [ "$1" = "shell" ] || return 1
  local command='"command"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)"' text=$2 found
  [[ $2 =~ $command ]] && text=${BASH_REMATCH[1]}
  local edge='(^|[^A-Za-z0-9_.-]|\\[nrt])'
  local gitcp="${edge}git(\.exe)?([^A-Za-z0-9_.-]|\\\\[nrt])(.*([^A-Za-z0-9_-]|\\\\[nrt]))?(commit|push)([^A-Za-z0-9_-]|$)"
  shopt -s nocasematch
  [[ $text =~ $gitcp ]] && found=0 || found=1
  shopt -u nocasematch
  return $found
}

# refuse_cannot_run WHY: the refusal of a commit or push while the guards cannot run, one JSON line on stdout.
refuse_cannot_run() {
  local why=${1//\\/\\\\}
  why=${why//\"/\\\"}
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"brain guard: the guards cannot run (%s), so the public and secrets checks refuse git commit and git push: run brain update (or the installer, install.ps1 -Apply), then retry. The SessionStart health says the same."}}\n' "$why"
}

[ "${BASH_SOURCE[0]}" = "$0" ] || return 0
root="${CLAUDE_PLUGIN_ROOT:-${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/..}"
IFS= read -r -d '' input  # the hook's JSON, without $(cat)'s fork
needs_python "${1:-}" "$input" || { selftime_bash "hook guard ${1:-} [bash]"; exit 0; }

home="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}"
brain_py=
brain_python "${BRAIN_PYTHON:-}" "$home/venv/Scripts/python.exe" "$home/venv/bin/python" python3 python && BRAIN_HOOK_T0=$brain_t0 "$brain_py" -X utf8 -I "$root/hooks/guard.py" "${1:-}" <<<"$input" 2>/dev/null && exit 0
# here no Python was found, or the one found failed: guard.py's main never fails, so it could not import brain
why="no Python 3 found (BRAIN_PYTHON, <BRAIN_HOME>/venv, python3, python)"
[ -n "$brain_py" ] && why="$brain_py cannot import brain"
[ -n "$brain_py" ] && [ "$brain_py" = "${BRAIN_PYTHON:-}" ] && why="$why; BRAIN_PYTHON chose it: fix or unset BRAIN_PYTHON"
selftime_bash "hook guard ${1:-} [cannot run]" 1
commits_or_pushes "${1:-}" "$input" && refuse_cannot_run "$why"
exit 0
