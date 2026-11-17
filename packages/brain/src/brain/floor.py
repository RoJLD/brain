"""The locked floor (wi-brain-unadopted-floor; spec-brain-one-brain 4.8, the owner's R21): the few rules no level ever
overrides, and the guard's refusals that hold them.

- **A locked rule** is a line of the owner's rules (config.json ``rules``) that carries the marker ``<!-- lock -->``
  (or ``<!-- lock: ID -->``, the decision that locked it, ID of ASCII letters, digits, ``_``, ``.`` and ``-``), an
  HTML comment that Markdown does not show. :func:`locked` returns those lines without the marker, as inject-rules.sh
  reads them. A machine that gets only the floor (``floor.only``) is injected these lines alone (inject-rules.sh).
- **The floor's refusals** (brain.guards, guard ``floor``): a ``git push`` to ``main`` or ``master`` is check
  ``main``: a refspec's destination (``HEAD`` and ``@`` read as the current branch, ``refs/heads/`` or ``heads/``
  dropped), a deletion of it, every branch (``--all``, ``--branches``), a matching push (``:``) or a refspec with
  ``*``, and with no refspec what git sends then (the remote's ``remote.<name>.push``, else ``push.default``:
  ``matching`` every branch, ``upstream`` the current branch's upstream, else the current branch). A forced push is
  check ``force``: ``--force``, ``--force-with-lease``, ``--force-if-includes``, ``--mirror`` (or any unambiguous
  prefix of them, as git reads its long options), ``f`` in a group of short options (``-uf``, ``-4f``; not after
  ``o``, whose value is attached), a refspec starting with ``+``. A secret in a commit is the secrets guard's
  already. They run under config.json ``floor.refuse: true`` (off by default: refusals this release adds) or
  ``floor.only: true``; ``BRAIN_GUARD_ALLOW=floor`` (or ``floor:main``, ``floor:force``) lifts them, the owner's.
- **Floor only** (config.json ``floor.only: true``): the machine gets the floor and nothing else: only the locked
  rules are injected, after :data:`ONLY_LINE`; the guard runs the floor's refusals, the secrets and configuration
  checks, the override protection (the guards' override, the usage allow file, the chain roots, and config.json
  itself) and the session-settings and scheduled-task tool checks; the memory notes are not synced, either way. How
  a machine or a project enters it on its own (a machine with no anchor in the owner's brain, a project until its
  merge phase) waits on the owner's answer; meanwhile the owner sets it.

Standard library only: the guard hook reads it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

SPACE = r"[ \t\n\r\f\v]"   # bash's [[:space:]] in the C locale, which inject-rules.sh reads the marker in
LOCK = re.compile(rf"{SPACE}*<!--{SPACE}*lock(?::{SPACE}*([A-Za-z0-9_.-]+))?{SPACE}*-->")
BRANCHES = ("main", "master")   # what no session pushes to (the owner merges by PR)
HEAD = ("HEAD", "@")            # the current branch, as a refspec names it
HEADS = re.compile(r"^(?:refs/)?heads/")
FORCE_FLAGS = ("--force", "--force-with-lease", "--force-if-includes", "--mirror")
EVERY_BRANCH = ("--all", "--branches")
DELETE = ("--delete", "-d")
NO_DEFAULT = {"--tags", "--mirror", *EVERY_BRANCH, *DELETE}   # pushes that send no default refspec
# git push's long options (git push -h, git 2.46): git takes any unambiguous prefix of one (--force-w, --mi).
PUSH_LONG = ("verbose", "quiet", "repo", "all", "branches", "mirror", "delete", "tags", "dry-run", "porcelain",
             "force", "force-with-lease", "force-if-includes", "recurse-submodules", "thin", "receive-pack", "exec",
             "set-upstream", "progress", "prune", "verify", "follow-tags", "signed", "atomic", "push-option", "ipv4",
             "ipv6")
LONG_OPTIONS = (*PUSH_LONG, *(f"no-{o}" for o in PUSH_LONG if o not in ("verify", "ipv4", "ipv6")), "no-verify")
ONLY_LINE = ("Floor only (config.json floor.only): this machine gets the locked rules alone, until it is adopted; "
             "the guard applies only the floor's refusals, the secrets and configuration checks, the override "
             "protection and the session-settings and scheduled-task checks, and the memory notes are not synced.")

# --- what the guard watches while the floor is on (brain.floorguard; reviews of wi-brain-unadopted-floor) ---------
# What turns every guard off for later sessions, set in the environment or Claude Code's settings: the interpreter
# guard.sh runs, the test marker that stops brain.paths.brain_home, another settings folder for Claude Code, and the
# settings key that disables every hook. Refused under guards.owner_strict and while the floor is on.
GUARD_OFF = r"BRAIN_PYTHON|PYTEST_CURRENT_TEST|CLAUDE_CONFIG_DIR|disableAllHooks"
# GUARD_OFF and what chooses the config.json the guard reads or the Python guard.sh finds: a name of the Brain's
# own, and HOME, USERPROFILE and PATH only where they are set (an assignment, a JSON key, setx, a registry name, the
# first argument of SetEnvironmentVariable), never where they are read ($HOME, ${HOME}, %USERPROFILE%). Matched on
# unspelled() text, case aside.
FLOOR_ENV = (r"BRAIN_CONFIG|CLAUDE_BRAIN_DIR|BRAIN_PERSONAL|BRAIN_HOME|CLAUDE_PLUGIN_ROOT|BASH_ENV|SHELLOPTS|"
             r"BASHOPTS|XDG_CONFIG_HOME|GIT_CONFIG\w*|" + GUARD_OFF +
             r"|(?-i:(?<![\w$%])(?<!\$\{)(?:HOME|USERPROFILE|ENV)\s*[=:,])|(?<![\w$%])(?<!\$\{)PATH\s*[:,]"
             r"|(?:\bsetx\s+|-name\s+|/v\s+)(?:HOME|USERPROFILE|PATH|ENV)\b")
# Round 8 #1: what an edit of a settings file adds (brain.floorguard._edit, on unspelled() text) that changes a call
# after the guard judged it or the programs every command runs: a PreToolUse or PermissionRequest hook (its
# updatedInput replaces the input the guard saw; a locked machine's managed allowManagedHooksOnly blocks it as well), and
# the env keys that pick a shell or git.
SETTINGS_KEYS = (r"(?<![\w$%])(?:PreToolUse|PermissionRequest|CLAUDE_CODE_GIT_BASH_PATH|CLAUDE_CODE_SHELL\w*|SHELL|"
                 r"GIT_EXEC_PATH|ComSpec|PATHEXT|SystemRoot|NoDefaultCurrentDirectoryInExePath|PS4)\s*:")
# Round 9 #1: settings `env` values reach every command Claude Code starts, after the guard judged it (BASH_FUNC_git%%
# redefines git in the Bash tool's bash; GIT_EXTERNAL_DIFF, GIT_SSH_COMMAND, GIT_DIR change what git runs). While the
# floor is on, a settings write adds only these names to `env` (brain.floorguard._edit), each with why it is harmless.
ENV_ALLOWED = {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "turns Claude Code's own telemetry on; runs nothing",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "where Claude Code's telemetry goes; read by Claude Code, not by a command",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "the telemetry's protocol",
    "OTEL_LOGS_EXPORTER": "the telemetry's log exporter",
    "OTEL_METRICS_EXPORTER": "the telemetry's metrics exporter",
    "OTEL_METRIC_EXPORT_INTERVAL": "the telemetry's interval",
    "DISABLE_TELEMETRY": "turns telemetry off",
    "DISABLE_ERROR_REPORTING": "turns error reports off",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "turns Claude Code's optional traffic off",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "a model limit",
    "MAX_THINKING_TOKENS": "a model limit",
    "BASH_DEFAULT_TIMEOUT_MS": "the Bash tool's timeout, read by Claude Code",
    "BASH_MAX_TIMEOUT_MS": "the Bash tool's longest timeout, read by Claude Code",
    "BRAIN_READ_HINT": "turns the read hint off (a hint, never a refusal)",
    "BRAIN_WAIT_HINT": "turns the wait hint off (a hint, never a refusal)",
    "BRAIN_BUDGET_WATCH": "turns the budget reminder off (a reminder, never a refusal)",
}
# Round 9 #2: a skill's, a custom command's or an agent's file, whose frontmatter `hooks:` run beside the guard (project
# and home .claude folders).
CUSTOMIZATION = re.compile(r"(?i)[\\/]\.claude[\\/](?:skills|commands|agents)[\\/]")
FRONTMATTER_HOOKS = re.compile(r"(?m)^[ \t]*['\"]?hooks['\"]?[ \t]*:")


# Round 10 #3: the top-level keys a settings write may add or change while the floor is on, each with why it runs
# nothing; every other key (apiKeyHelper, otelHeadersHelper, awsAuthRefresh, awsCredentialExport, gcpAuthRefresh,
# statusLine, fileSuggestion: shell command lines Claude Code runs with no tool call; extraKnownMarketplaces and
# enabledPlugins, which bring a plugin's MCP servers) is refused, a change of its value included.
SETTINGS_ALLOWED = {
    "$schema": "the editor's schema link",
    "permissions": "allow, ask and deny rules: the guard still judges every call they allow",
    "env": "within ENV_ALLOWED",
    "model": "the session's model",
    "effortLevel": "the model's effort",
    "alwaysThinkingEnabled": "the model's thinking",
    "outputStyle": "how replies read",
    "language": "the replies' language",
    "spinnerTipsEnabled": "a display setting",
    "agentPushNotifEnabled": "the app's notifications",
    "skipWorkflowUsageWarning": "a notice the app shows",
    "cleanupPeriodDays": "how long transcripts are kept",
}


def env_added(target, before: str, after: str) -> str:
    """What a settings JSON write (``target`` resolved: a stream's name dropped) adds that the floor refuses (rounds
    9 #1, 10 #3): an `env` name ENV_ALLOWED does not hold, or a top-level key SETTINGS_ALLOWED does not hold that it
    adds or changes; '' when none. A file the write leaves unreadable as JSON reads as adding one."""
    import json
    if not str(target).lower().endswith(".json"):
        return ""

    def read(text: str):
        try:
            data = json.loads(text) if text.strip() else {}
        except ValueError:
            return None
        return data if isinstance(data, dict) else None
    now, was = read(after), read(before) or {}
    if now is None:
        return "settings the guard cannot read as a JSON object"
    key = next((k for k in sorted(now) if k not in SETTINGS_ALLOWED and now[k] != was.get(k, object())
                and not _plugins_off(now[k] if k == "enabledPlugins" else None, was.get(k))), "")
    if key:
        return key
    env, env_was = now.get("env"), was.get("env") if isinstance(was.get("env"), dict) else {}
    if env is not None and not isinstance(env, dict):
        return "env"
    return next((n for n in sorted(set(env or {}) - set(env_was)) if n not in ENV_ALLOWED), "")


def _plugins_off(now, was) -> bool:
    """Whether an enabledPlugins change only turns plugins off (the core plugin's own check is floorguard's)."""
    was = was if isinstance(was, dict) else {}
    return isinstance(now, dict) and all(v is False for k, v in now.items() if was.get(k, object()) != v)


def _has_key(node, name: str) -> bool:
    if isinstance(node, dict):
        return any(str(k).lower() == name or _has_key(v, name) for k, v in node.items())
    return isinstance(node, list) and any(_has_key(v, name) for v in node)


def frontmatter_hooks(tool: str, target, before: str, after: str) -> str | None:
    """A write that adds a `hooks` key, at any depth, to a skill's, command's or agent's frontmatter (CUSTOMIZATION;
    read as YAML: a flow mapping, a merge key; round 10 #5), else None."""
    def has(text: str) -> bool:
        m = re.match(r"﻿?\s*---[ \t]*\r?\n(.*?)\r?\n---", text or "", re.S)
        if not m:
            return False
        try:
            from .graph import load_yaml
            return _has_key(load_yaml(m.group(1)), "hooks") or bool(FRONTMATTER_HOOKS.search(unspelled(m.group(1))))
        except Exception:   # noqa: BLE001 - what YAML cannot read is judged on its text: fail closed
            return bool(re.search(r"(?i)hooks", unspelled(m.group(1))))
    if has(after) and not has(before):
        return (f"{tool} refused: it adds hooks to {target}'s frontmatter, which run beside the guard and can change "
                "the call it judged")
    return None
# The variables no command sets while the floor is on, in any form (a prefix NAME=, export, declare, printf -v, read,
# env, ${NAME:=}, (( NAME = )), PowerShell's $env:, ${env:} and its env: provider, SetEnvironmentVariable): git's that
# change its configuration, repository or the programs it runs (GIT_EDITOR, GIT_SEQUENCE_EDITOR and GIT_PAGER pass
# as true, : or cat), what chooses git's global configuration (HOME, XDG_CONFIG_HOME), what bash reads before a
# script (BASH_ENV, SHELLOPTS, BASHOPTS), PATH, the Brain's own, and Claude Code's that choose its settings or plugin.
GIT_VARS = (r"GIT_CONFIG\w*|GIT_DIR|GIT_WORK_TREE|GIT_INDEX_FILE|GIT_COMMON_DIR|GIT_NAMESPACE|GIT_\w*_DIRECTORY|"
            r"GIT_\w*_DIRECTORIES|GIT_EXEC_PATH|GIT_SSH\w*|GIT_ASKPASS|GIT_EXTERNAL_DIFF|GIT_TEMPLATE_DIR|"
            r"GIT_PROXY_COMMAND|GIT_ALLOW_PROTOCOL|GIT_(?:SEQUENCE_)?EDITOR(?!=(?:true|:|cat)\b)|GIT_PAGER(?!=(?:true|:|cat|less)\b)")
WATCHED_VARS = (GIT_VARS + r"|HOME|USERPROFILE|XDG_CONFIG_HOME|BASH_ENV|SHELLOPTS|BASHOPTS|PATH|BRAIN_\w+|"
                r"CLAUDE_CONFIG_DIR|CLAUDE_PLUGIN_ROOT|CLAUDE_BRAIN_DIR|CLAUDE_PROJECT_DIR")
_START = r"(?:^|(?<=[\s;&|(]))"
ENV_ASSIGN = re.compile(
    rf"{_START}(?:{WATCHED_VARS})\+?=|"                                                   # NAME=, NAME+= (bash, cmd's set)
    rf"\b(?:export|declare|typeset|readonly|read)\b[^;&|\n]*?(?<![\w${{])(?:{WATCHED_VARS})\b|"
    rf"\bprintf\s+-v\s*(?:{WATCHED_VARS})\b|"
    rf"\$\{{(?:{WATCHED_VARS}):?=|\(\(\s*(?:{WATCHED_VARS})\s*[-+*/]?=|"                 # ${NAME:=x}, (( NAME = 1 ))
    rf"(?<![\w-])set\s(?:[^;&|\n]*\s)?(?:-[A-Za-z]*a[A-Za-z]*|allexport)(?![\w-])|"     # set -a, set -e -o allexport
    rf"\bshopt\b[^;&|\n]*\ballexport\b|"                                                  # shopt -so allexport
    rf"\b(?:for|select)\s+(?:{WATCHED_VARS})\b(?=\s*(?:in\b|;|\n|do\b|$))|"                # for NAME in, select NAME in
    rf"\bgetopts\s+\S+\s+(?:{WATCHED_VARS})\b|"
    rf"\b(?:mapfile|readarray)\b[^;&|\n]*?(?<![\w$-])(?:{WATCHED_VARS})\b|"
    rf"(?i:\$\{{?env:(?:{WATCHED_VARS})\}}?\s*(?:[+-]?=|,))|"                            # $env:X = , ${env:X} =, $env:X, $y =
    rf"(?i:(?<![$\{{\w])env:[\\/]?(?:{WATCHED_VARS})\b)|"                                # the env: provider: Env:\X, Env:/X, 'env:X'
    rf"(?i:\b(?:rename-item|copy-item|move-item|rni|ren|cpi|copy|mi|move)\b[^;|\n]*\benv:)|"
    rf"(?i:\benv:[\\/]?[^;|\n]*-name\s+(?:{WATCHED_VARS})\b)|"
    rf"(?i:\benv:[^;\n]*\|\s*(?:rename-item|rni|ren|copy-item|cpi|copy|move-item|mi|move|set-item|si|new-item|ni)\b)|"
    rf"(?i:\b(?:new-item|ni|set-item|si|rename-item|rni|ren)\b[^;|\n]*-(?:new)?name\s+(?:{WATCHED_VARS})\b)|"
    rf"(?i:\.Environment(?:Variables)?\s*(?:\[|\.(?:Add|Item|set_Item)\s*\()\s*(?:{WATCHED_VARS})\b)|"
    rf"(?i:SetEnvironmentVariable\s*\(\s*(?:{WATCHED_VARS})\s*,)")
# An assignment whose name the guard cannot read (a variable, a call): refused while the floor is on.
ENV_DYNAMIC = re.compile(r"\b(?:export|declare|typeset|printf\s+-v)\s+(?:-\w+\s+)*[^\s;=]*[$(`]|"
                         r"(?i:\benv:[^\s;=]*[$(]|\$\{env:[^}]*[$(]|\b(?:set-item|new-item|si|ni)\s+\$)")
# git's global options a command may give while the floor is on (-c and --config-env are refused on their own).
GIT_GLOBAL_OK = {"-C", "--no-pager", "-P", "--paginate", "-p", "--no-optional-locks", "--literal-pathspecs",
                 "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs", "--no-advice", "-c", "--config-env"}
# git's own configuration and ref files: an alias, an include or a mirror written there changes what a push does, a
# ref written there what HEAD or origin/main names (brain.floor.effective reads the floor from both).
GIT_CONFIG_FILES = re.compile(r"(?i)(?:^|[\\/])(?:\.gitconfig|\.git[\\/]config(?:\.worktree)?|git[\\/]config|"
                              r"\.git[\\/](?:.*[\\/])?(?:refs[\\/].*|packed-refs|HEAD))$")
# The configuration keys a session does not set while the floor is on (git config): aliases, includes, remotes,
# push's own keys, URL rewrites, and what makes git write elsewhere or run a program (core.*, filters, diff and merge
# drivers, credential helpers, editors, pagers, gpg, upload-pack and receive-pack; round 6: the transports a protocol
# allows (ext::), submodules' update commands, browsers, interactive filters, man viewers, instaweb, send-email, init's
# templates, ssh's variant, trailer commands and configured hooks).
PUSH_KEYS = re.compile(r"(?i)^(?:alias\..+|include(?:if\..+)?\.path|remote\..+|push\..+|url\..+|core\..+|filter\..+|"
                       r"diff\..+|merge\..+\.driver|credential.*|sequence\.editor|gpg\..+|uploadpack\..+|"
                       r"receivepack\..+|difftool\..+|mergetool\..+|pager\..+|branch\..+|protocol\..+|"
                       r"submodule\..+|interactive\..+|browser\..+|web\..+|man\..+|instaweb\..+|sendemail\..+|"
                       r"init\..+|ssh\..+|trailer\..+|hook\..+|imap\..+)$")
# The keys of PUSH_KEYS an ordinary repo sets that neither run a program nor redirect a write (round 6, #12): line
# endings, long paths, the file mode, case, quoting, the diff and merge tool's name, a branch's description; and
# credential.helper given one of the usual helpers, whole (CREDENTIAL_HELPERS; round 7: git runs a helper's value
# through the shell, so "store ;cp ..." ran cp).
SAFE_KEYS = re.compile(r"(?i)^(?:core\.(?:autocrlf|longpaths|filemode|ignorecase|eol|quotepath|safecrlf|precomposeunicode)|"
                       r"diff\.tool|merge\.tool|diff\.guitool|merge\.guitool|branch\..+\.description)$")
CREDENTIAL_HELPERS = {"manager", "manager-core", "store", "cache", "wincred", "osxkeychain", "libsecret", ""}
CREDENTIAL_VALUE = re.compile(r"(?i)^\s*(?:" + "|".join(sorted(h for h in CREDENTIAL_HELPERS if h)) +
                              r")?(?:\s+--[\w-]+(?:=[\w./:~-]*)?)*\s*$")   # its options alone: nothing for a shell
# git options that write a file or run a program, refused under the floor whatever the subcommand: an output file,
# a pager, an upload-pack or receive-pack program, a command to run, an external diff or textconv.
GIT_RUNNING_OPTS = ("--output", "--open-files-in-pager", "--upload-pack", "--receive-pack", "--exec", "--ext-diff",
                    "--textconv", "--extcmd", "--unsafe-paths")
# Per subcommand, the short options that do the same: grep -O (a pager), rebase -x (a command), ls-remote and clone
# -u (an upload-pack), difftool -x and -t (a tool). format-patch -o passes (round 6, #12): it writes NNNN-*.patch
# files, never a settings file.
GIT_RUNNING_SHORT = {"grep": ("-O",), "rebase": ("-x",), "ls-remote": ("-u",), "clone": ("-u",),
                     "difftool": ("-x", "-t")}
# git subcommands that run what they are given: bisect run, submodule foreach, filter-branch, mergetool.
GIT_RUNNERS = {"bisect": "run", "submodule": "foreach", "filter-branch": "", "filter-repo": "", "mergetool": "",
               "update-ref": ""}
# What git may run in the checkout that holds config.json while the floor is on: reads, fetch, push (judged on its
# own), worktree, branch and tag (they leave its files alone); git config and git remote only to read, git pull only
# as `git pull --ff-only` with no remote nor refspec (brain.floorguard._checkout).
CHECKOUT_SAFE = {"status", "log", "diff", "show", "fetch", "rev-parse", "ls-files", "ls-tree", "ls-remote",
                 "cat-file", "blame", "grep", "describe", "for-each-ref", "show-ref", "rev-list", "merge-base",
                 "shortlog", "name-rev", "check-ignore", "count-objects", "var", "help", "version", "push",
                 "worktree", "branch", "tag"}
# git's subcommands the floor never reads as an alias (a word not here is looked up in alias.*).
GIT_BUILTIN = {*CHECKOUT_SAFE, "config", "remote", "add", "commit", "pull", "init", "clone", "send-pack",
               "symbolic-ref", "update-ref",
               "notes", "submodule", "checkout", "restore", "stash", "reset", "clean", "switch", "rm", "mv",
               "read-tree", "checkout-index", "rebase", "cherry-pick", "revert", "am", "apply", "merge", "bisect",
               "sparse-checkout", "filter-branch", "gc", "prune", "reflog", "maintenance"}


def unspelled(text: str) -> str:
    """``text`` with what only spells a name differently taken out: JSON's ``\\uXXXX`` escapes decoded, a string
    concatenation ('A'+'B') joined, and the quotes, carets and backticks a shell or cmd drops (BRAIN_GUARD''_ALLOW,
    BRAIN_GUARD^_ALLOW)."""
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r"['\"]\s*\+\s*['\"]", "", text)
    return re.sub(r"['\"^`]", "", text)


def locked(text: str) -> list[str]:
    """The lines of ``text`` that carry the lock marker, every marker taken out, in their order (lines split on LF, a
    CR dropped, a tab made a space, as inject-rules.sh reads them)."""
    return [LOCK.sub("", line).rstrip(" \t\n\r\f\v") for line in text.replace("\r", "").replace("\t", " ").split("\n")
            if LOCK.search(line)]


def settings(data: dict | None) -> dict:
    """config.json's ``floor``: {refuse, only}, each a bool (anything else is false)."""
    section = data.get("floor") if isinstance(data, dict) else None
    section = section if isinstance(section, dict) else {}
    return {"refuse": section.get("refuse") is True, "only": section.get("only") is True}


# --- where the floor is read, and the lock that holds it (review rounds 6-7: the operating system's lock) ----------
# A guard that parses the shell cannot stop a session running as the same user: the session can rewrite whatever the
# guard reads or runs from, and any folder in the user's profile can be renamed through its parent. So on a locked
# machine the floor and the guard live outside the profile, in folders whose parents only an administrator writes:
# brain floor lock (brain.floorlock, an elevated step of the owner's) writes the machine's lock file (lock_dir(): the
# floor's copy, which is the authority), installs the guard as a system component (guard_dir(): an interpreter, the
# guard's code, its manifest of hashes) and declares its hooks in Claude Code's managed settings (managed_file()).
# config.json is then only compared to the locked floor: a difference refuses every call until the owner locks again.
ON = {"refuse": True, "only": False}   # what an unreadable or unparsable config.json says: the floor on (fail closed)
ONLY = {"refuse": True, "only": True}  # what an unreadable lock file says
LOCK_FILE = "floor-lock.json"          # in lock_dir(): {"format", "floor", "config", "brain_home", "checks", ...}
LOCK_FORMAT = "brain.floor-lock/v2"
MANIFEST = "manifest.json"             # in guard_dir(): {relative path: sha256} of every file of the guard
MANAGED_NAME = "brain-floor.json"      # in managed_dir()/managed-settings.d: the guard's hooks
# The tests' scratch folders; never environment variables (a session sets those).
LOCK_DIR: Path | None = None
GUARD_DIR: Path | None = None
MANAGED_DIR: Path | None = None
PROFILE_DIR: Path | None = None   # the account's profile folder brain floor lock's ACL step reads (profile())
# What a session must not hold on a locked path: write or append data, write extended attributes, delete a folder's
# entries, delete it, change its ACL or its owner (FILE_WRITE_DATA, FILE_APPEND_DATA, FILE_WRITE_EA,
# FILE_DELETE_CHILD, DELETE, WRITE_DAC, WRITE_OWNER; a folder's add-file and add-folder are the first two).
WRITE_RIGHTS = 0x2 | 0x4 | 0x10 | 0x40 | 0x10000 | 0x40000 | 0x80000
# Who may own a locked path: Administrators, SYSTEM, TrustedInstaller.
TRUSTED_OWNERS = {"S-1-5-32-544", "S-1-5-18", "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"}


def acl_wanted(data, nt: bool | None = None) -> bool:
    """Whether config.json's data asks the lock's ACL step (brain.flooracl): ``floor.acl: true`` under floor.only, on
    Windows (``nt``): a POSIX machine sharing that config.json locks without it."""
    section = data.get("floor") if isinstance(data, dict) else None
    return (os.name == "nt" if nt is None else nt) and isinstance(section, dict) and section.get("acl") is True \
        and settings(data)["only"]


def acl_loose(path, writable=None) -> str:
    """Why a path of the lock's ACL step is not held ('' when it is): gone, a link or a junction (or under one),
    within this session's reach, or owned by another than the administrators (a folder a session made again in its
    place, its DACL read-only for itself)."""
    if not os.path.lexists(path):
        return "missing"
    if _real(path) != os.path.normcase(os.path.abspath(path)):
        return "a link or a junction"
    if (writable or globals()["writable"])(path):
        return "writable"
    if os.name == "nt" and owner(path) not in TRUSTED_OWNERS:
        return "not owned by the administrators"
    return ""


def _home_moved(home: str) -> str:
    """Which of USERPROFILE and HOME (Git Bash's /c/x read as C:/x) names another folder than the profile that holds
    ``home`` (~/.claude, the ACL step's): Claude Code would read its settings from there."""
    want = os.path.normcase(os.path.abspath(os.path.dirname(home)))
    for name in ("USERPROFILE", "HOME"):
        value = os.environ.get(name, "")
        value = re.sub(r"^/([A-Za-z])(?=/|$)", lambda m: m.group(1) + ":", value)
        if value and os.path.normcase(os.path.abspath(value)) != want:
            return name
    return ""


def _acl_held(lock: dict, writable) -> str:
    """'' when the lock's ACL step (its ``acl``) still holds for this session: its account is this process's (one that
    cannot be read is not), Claude Code reads the folder it locked (no CLAUDE_CONFIG_DIR, USERPROFILE and HOME the
    profile), and each of its paths is held (:func:`acl_loose`)."""
    a = lock.get("acl")
    if not isinstance(a, dict):
        return ""
    me = account()
    if me != a.get("account"):
        return f"the lock's ACL step denies {a.get('account')}, not this session's account {me or '(unread)'}"
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        return "CLAUDE_CONFIG_DIR moves Claude Code's settings out of the folder the lock's ACL step holds"
    moved = _home_moved(str(a.get("home") or ""))
    if moved:
        return f"{moved} moves Claude Code's settings out of the profile the lock's ACL step holds"
    for p in [*a.get("files", []), *a.get("trees", []), *a.get("folders", [])]:
        why = acl_loose(p, writable)
        if why:
            return f"{p} is {why}"
    return ""


def _union(*states: dict) -> dict:
    return {"refuse": any(s["refuse"] for s in states), "only": any(s["only"] for s in states)}


def lock_dir() -> Path:
    """The machine's lock folder: <ProgramData>/Brain on Windows (the folder the system names, not the environment's
    ProgramData), /etc/brain elsewhere; only an administrator writes there once brain floor lock has run."""
    if LOCK_DIR is not None:
        return Path(LOCK_DIR)
    return Path(_hklm_folder("ProgramData")) / "Brain" if os.name == "nt" else Path("/etc/brain")


def guard_dir() -> Path:
    """Where brain floor lock installs the guard: <Program Files>/Brain/guard (the folder HKLM names), /opt/brain/guard
    elsewhere."""
    if GUARD_DIR is not None:
        return Path(GUARD_DIR)
    return Path(_hklm_folder("ProgramFilesDir")) / "Brain" / "guard" if os.name == "nt" else Path("/opt/brain/guard")


def managed_dir() -> Path:
    """Claude Code's managed settings folder, as its documentation names it (Deploy managed settings): C:\\Program
    Files\\ClaudeCode on Windows (a fixed path, not the environment's), /Library/Application Support/ClaudeCode on
    macOS, /etc/claude-code elsewhere."""
    if MANAGED_DIR is not None:
        return Path(MANAGED_DIR)
    if os.name == "nt":
        return Path("C:\\Program Files\\ClaudeCode")
    import sys
    return Path("/Library/Application Support/ClaudeCode" if sys.platform == "darwin" else "/etc/claude-code")


def managed_file() -> Path:
    """The managed settings drop-in that declares the guard's hooks."""
    return managed_dir() / "managed-settings.d" / MANAGED_NAME


def profile(sid: str, fallback: bool = True) -> Path | None:
    """The profile folder of the account ``sid`` as the machine's registry names it (HKLM ProfileList's
    ProfileImagePath, %SystemDrive% read from HKLM: values only an administrator writes, and the right folder when an
    elevated step runs as another administrator than the account); else this process's home, or None when not
    ``fallback`` (the ACL step never guesses whose folder it locks)."""
    if PROFILE_DIR is not None:
        return Path(PROFILE_DIR)
    if os.name == "nt":
        try:
            import winreg
            nt = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{nt}\ProfileList\{sid}") as k:
                value = str(winreg.QueryValueEx(k, "ProfileImagePath")[0])
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, nt) as k:
                drive = os.path.splitdrive(str(winreg.QueryValueEx(k, "SystemRoot")[0]))[0] or "C:"
            value = re.sub(r"(?i)%SystemDrive%", lambda m: drive, value)
            if value and "%" not in value:
                return Path(value)
        except (OSError, ImportError, ValueError):
            pass
    return Path.home() if fallback else None


def sid_kind(sid: str) -> int:
    """The kind of account ``sid`` names (LookupAccountSid's SID_NAME_USE: 1 a user, 2 a group...); 0 when it cannot
    be looked up or off Windows."""
    if os.name != "nt":
        return 0
    try:
        import ctypes
        from ctypes import wintypes
        adv, k32 = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
        adv.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
        adv.LookupAccountSidW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, wintypes.LPWSTR,
                                          ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR,
                                          ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_int)]
        psid = ctypes.c_void_p()
        if not adv.ConvertStringSidToSidW(sid, ctypes.byref(psid)):
            return 0
        try:
            name, domain = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
            n, d, use = wintypes.DWORD(256), wintypes.DWORD(256), ctypes.c_int(0)
            if not adv.LookupAccountSidW(None, psid, name, ctypes.byref(n), domain, ctypes.byref(d), ctypes.byref(use)):
                return 0
            return use.value
        finally:
            k32.LocalFree(psid)
    except (OSError, AttributeError, ValueError):
        return 0


def account() -> str:
    """This process's account as a SID string (its token's user: the account a session runs as, when the plan is
    printed in a normal terminal); '' when it cannot be read or off Windows."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        adv, k32 = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD)]
        adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        token = wintypes.HANDLE()
        if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):   # TOKEN_QUERY
            return ""
        try:
            need = wintypes.DWORD(0)
            adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(need))   # TokenUser: a SID_AND_ATTRIBUTES
            buf = ctypes.create_string_buffer(need.value or 1)
            if not (need.value and adv.GetTokenInformation(token, 1, buf, need, ctypes.byref(need))):
                return ""
            sid, text = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0], wintypes.LPWSTR()
            if not adv.ConvertSidToStringSidW(sid, ctypes.byref(text)):
                return ""
            out = text.value or ""
            k32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
            return out
        finally:
            k32.CloseHandle(token)
    except (OSError, AttributeError, ValueError):
        return ""


def _hklm_folder(name: str) -> str:
    """A system folder as the machine's registry names it (``ProgramData``: HKLM ProfileList; ``ProgramFilesDir``:
    HKLM CurrentVersion), %SystemDrive% read from HKLM's SystemRoot: values only an administrator writes, read in well
    under a millisecond; else its default on C:. Never the environment, which a session sets."""
    default = {"ProgramData": "C:\\ProgramData", "ProgramFilesDir": "C:\\Program Files"}[name]
    try:
        import winreg
        nt = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        key = nt + r"\ProfileList" if name == "ProgramData" else r"SOFTWARE\Microsoft\Windows\CurrentVersion"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            value = str(winreg.QueryValueEx(k, name)[0])
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, nt) as k:
            drive = os.path.splitdrive(str(winreg.QueryValueEx(k, "SystemRoot")[0]))[0] or "C:"
        path = re.sub(r"(?i)%SystemDrive%", lambda m: drive, value)
        if path and "%" not in path:
            return path
    except (OSError, ImportError, ValueError):
        pass
    return default


def read_lock() -> dict | None:
    """The machine's lock file (brain floor lock): None when there is none, {"error": why} when it cannot be read or
    is not one (the floor then reads ONLY and the lock as broken)."""
    import json
    f = lock_dir() / LOCK_FILE
    try:
        if not f.exists():
            return None
        data = json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        return {"error": f"{f}: {type(exc).__name__}"}
    if not isinstance(data, dict) or data.get("format") != LOCK_FORMAT:
        return {"error": f"{f}: not a {LOCK_FORMAT} file (brain floor lock --apply writes one)"}
    return data


def effective(cfg, lock: dict | None = None) -> dict:
    """The floor as the guard holds it: the lock file's copy wherever a lock exists (an unreadable one says ONLY;
    config.json's, when it says more, makes unlocked() refuse every call), else config.json's (a file that exists but
    cannot be read or parsed says ON)."""
    local = settings(cfg.data) if not cfg.error else dict(ON)
    if lock is None:
        return local
    return _union(local, dict(ONLY) if lock.get("error") else settings({"floor": lock.get("floor")}))


def unlocked(cfg, fl: dict, lock: dict | None, writable=None) -> str:
    """Why the floor is not held, '' when it is or need not be: asked under floor.only and wherever a lock file
    exists. The lock must exist and be readable; its folder, its file, the guard's folder and manifest and the managed
    settings file it names present and out of this session's reach (``writable``: :func:`writable`); the manifest the
    one it hashed; and config.json the one it holds, with the floor it holds."""
    if not (fl["only"] or lock is not None):
        return ""
    if lock is None:
        return "this machine has no lock (brain floor lock has not been applied)"
    if lock.get("error"):
        return f"the lock file cannot be read ({lock['error']})"
    writable = writable or globals()["writable"]
    held = [str(lock_dir()), str(lock_dir() / LOCK_FILE), *(lock.get("checks") or [])]
    return _reachable(held, writable, missing=True) or _manifest_changed(lock) or _held_config(cfg, lock) \
        or _acl_held(lock, writable)


def _manifest_changed(lock: dict) -> str:
    """'' when the guard's manifest is the one the lock hashed."""
    f = Path(str(lock.get("guard") or "")) / MANIFEST
    try:
        if file_hash(f) == lock.get("manifest"):
            return ""
    except OSError:
        pass
    return f"the guard's manifest {f} is not the one the lock hashed"


def file_hash(path) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _held_config(cfg, lock: dict) -> str:
    """'' when the config.json the guard reads is the one the lock holds and gives the floor it holds."""
    held = str(lock.get("config") or "")
    if cfg.file is None or not held or not _same(cfg.file, held):
        return f"the guard reads {cfg.file or 'no config.json'}, the lock holds {held or 'none'}"
    local = settings(cfg.data) if not cfg.error else dict(ON)
    locked = settings({"floor": lock.get("floor")})
    if local != locked:
        return (f"config.json's floor (refuse={local['refuse']}, only={local['only']}) is not the locked one "
                f"(refuse={locked['refuse']}, only={locked['only']}): the owner locks it again")
    if not cfg.error and acl_wanted(cfg.data) != isinstance(lock.get("acl"), dict):
        return (f"config.json's floor.acl ({acl_wanted(cfg.data)}) is not the locked one "
                f"({isinstance(lock.get('acl'), dict)}): the owner locks it again")
    return ""


def _reachable(paths: list, writable, missing: bool = False) -> str:
    """The first of ``paths`` this session can change (or, ``missing``, that is gone), said; '' when none."""
    for p in paths:
        if missing and (not isinstance(p, str) or not os.path.lexists(p)):
            return f"{p} is missing"
        if writable(p):
            return f"{p} is writable by this session"
    return ""


def _real(path) -> str:
    return os.path.normcase(resolve(str(path)))


# Round 8 #2: a network path (\\host\share, //host/share, \\?\UNC\host\share) whose resolution can take tens of seconds
# (an unreachable host), which a call could use to run the guard past its hook's timeout. \\?\C:\ and \\.\C:\ are local.
# Round 9 #4: and every \\?\ or \\.\ (//?/, //./) path but a drive letter's: GLOBALROOT, Device\Mup, a volume GUID.
UNC = re.compile(r"^[\\/]{2}(?![?.][\\/])|^[\\/]{2}[?.][\\/](?![A-Za-z]:(?:[\\/]|$))", re.I)


def resolve(path: str) -> str:
    """os.path.realpath, but a network path is judged as written (normalised, never resolved: round 8 #2)."""
    if re.match(r"^[\\/]{2}[?.][\\/][A-Za-z]:(?:[\\/]|$)", path):   # round 11 #6: \\?\C:\ is C:\, kept or not
        path = path[4:]
    absolute = os.path.abspath(path)
    return os.path.normpath(absolute) if UNC.match(path) or UNC.match(absolute) else os.path.realpath(absolute)


def git() -> str:
    """The git the guard runs (round 8 #8): the one the lock file names (an administrator's, checked by brain floor
    lock), else the PATH's, never the working directory's (NoDefaultCurrentDirectoryInExePath)."""
    lock = read_lock()
    if lock and not lock.get("error") and isinstance(lock.get("git"), str) and os.path.isabs(lock["git"]):
        return lock["git"]
    # PATH's absolute folders only, in order: shutil.which searches the working directory first on Windows (Python
    # before 3.12 whatever NoDefaultCurrentDirectoryInExePath says), and a relative entry is the working directory too.
    exts = [e for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e] if os.name == "nt" else [""]
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if folder and os.path.isabs(folder):
            for ext in exts:
                p = os.path.join(folder, "git" + ext)
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    return p
    return "git"


def _same(a, b) -> bool:
    return _real(a) == _real(b)


def _within(path, folder) -> bool:
    p, f = _real(path), _real(folder)
    return p == f or p.startswith(f.rstrip("\\/") + os.sep)


def writable(path) -> bool:
    """Whether this process's token may change ``path``: write or append to it, delete it, change its ACL or owner,
    add or delete a folder's entries (:data:`WRITE_RIGHTS`, read from its security descriptor: on Windows os.access
    reads only the read-only attribute); POSIX: not owned by root, or writable. True when it cannot be told."""
    try:
        return _writable_nt(str(path)) if os.name == "nt" else _writable_posix(str(path))
    except Exception:   # any failure reads as reachable: the guard fails closed
        return True


def owner(path) -> str:
    """Who owns ``path``: its owner's SID on Windows (S-1-5-32-544 for Administrators), its uid elsewhere; '' when
    it cannot be read."""
    try:
        if os.name != "nt":
            return str(os.lstat(path).st_uid)
        import ctypes
        from ctypes import wintypes
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        adv.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD)]
        adv.GetSecurityDescriptorOwner.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                                   ctypes.POINTER(wintypes.BOOL)]
        adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        need = wintypes.DWORD(0)
        adv.GetFileSecurityW(str(path), 0x1, None, 0, ctypes.byref(need))   # OWNER_SECURITY_INFORMATION
        sd = ctypes.create_string_buffer(need.value or 1)
        sid, defaulted, text = ctypes.c_void_p(), wintypes.BOOL(), wintypes.LPWSTR()
        if not (need.value and adv.GetFileSecurityW(str(path), 0x1, sd, need, ctypes.byref(need))
                and adv.GetSecurityDescriptorOwner(sd, ctypes.byref(sid), ctypes.byref(defaulted)) and sid.value
                and adv.ConvertSidToStringSidW(sid, ctypes.byref(text))):
            return ""
        out = text.value or ""
        ctypes.WinDLL("kernel32").LocalFree(ctypes.cast(text, ctypes.c_void_p))
        return out
    except (OSError, AttributeError, ValueError):
        return ""


def _writable_posix(path: str) -> bool:
    st = os.lstat(path)
    return st.st_uid != 0 or os.access(path, os.W_OK, follow_symlinks=False)


def _writable_nt(path: str) -> bool:
    """AccessCheck of the path's security descriptor against this process's token (impersonated), MAXIMUM_ALLOWED,
    the file object's generic mapping: whether any of WRITE_RIGHTS is granted."""
    import ctypes
    from ctypes import wintypes

    class MAPPING(ctypes.Structure):
        _fields_ = [("read", wintypes.DWORD), ("write", wintypes.DWORD), ("execute", wintypes.DWORD),
                    ("all", wintypes.DWORD)]

    adv, k32 = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    adv.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD)]
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.DuplicateToken.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)]
    adv.AccessCheck.argtypes = [ctypes.c_void_p, wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(MAPPING),
                                ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                                ctypes.POINTER(wintypes.BOOL)]
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    info = 0x1 | 0x2 | 0x4   # OWNER, GROUP and DACL_SECURITY_INFORMATION
    need = wintypes.DWORD(0)
    adv.GetFileSecurityW(path, info, None, 0, ctypes.byref(need))
    if not need.value:
        return True
    sd = ctypes.create_string_buffer(need.value)
    if not adv.GetFileSecurityW(path, info, sd, need, ctypes.byref(need)):
        return True
    token, imp = wintypes.HANDLE(), wintypes.HANDLE()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0002 | 0x0008, ctypes.byref(token)):   # DUPLICATE, QUERY
        return True
    try:
        if not adv.DuplicateToken(token, 2, ctypes.byref(imp)):   # SecurityImpersonation
            return True
        try:
            mapping = MAPPING(0x120089, 0x120116, 0x1200A0, 0x1F01FF)   # FILE_GENERIC_READ, _WRITE, _EXECUTE, ALL
            privs, plen = ctypes.create_string_buffer(1024), wintypes.DWORD(1024)
            granted, status = wintypes.DWORD(0), wintypes.BOOL(0)
            if not adv.AccessCheck(sd, imp, 0x02000000, ctypes.byref(mapping), privs, ctypes.byref(plen),
                                   ctypes.byref(granted), ctypes.byref(status)):   # MAXIMUM_ALLOWED
                return True
            return bool(granted.value & WRITE_RIGHTS)
        finally:
            k32.CloseHandle(imp)
    finally:
        k32.CloseHandle(token)


def long_option(name: str) -> str:
    """The git push long option ``name`` (``--x``, what comes before any ``=``) spells: itself when it is one, the one
    option it is an unambiguous prefix of, else ``name`` unchanged (git refuses an unknown or ambiguous one)."""
    word = name[2:]
    if not name.startswith("--") or not word or word in LONG_OPTIONS:
        return name
    hits = [o for o in LONG_OPTIONS if o.startswith(word)]
    return f"--{hits[0]}" if len(hits) == 1 else name


def _short_force(flag: str) -> bool:
    """Whether a group of short options (-f, -uf, -4f) holds f: it is read up to an o, whose value is attached
    (-oforce is a push option)."""
    if flag.startswith("--") or not flag.startswith("-"):
        return False
    for c in flag[1:]:
        if c == "f":
            return True
        if c == "o" or not (c.isascii() and c.isalnum()):
            return False
    return False


def forced(refspecs: list[str], flags: set[str]) -> str:
    """The flag or the refspec that forces a push, else ''."""
    for f in sorted(flags):
        if long_option(f) in FORCE_FLAGS or _short_force(f):
            return f
    return next((r for r in refspecs if r.startswith("+")), "")


def needs_current(refspecs: list[str], flags: set[str]) -> bool:
    """Whether reading a push needs the branch checked out: no refspec (and a push that sends the default), or one
    that names HEAD or @ alone."""
    if not refspecs:
        return not {long_option(f) for f in flags} & NO_DEFAULT
    return any(r.lstrip("+") in HEAD for r in refspecs)


def _destination(refspec: str, current: str) -> str:
    """The branch a refspec writes on the remote: SRC:DST's DST, else its SRC (HEAD or @: ``current``);
    refs/heads/ or heads/ dropped."""
    src, colon, dst = refspec.lstrip("+").partition(":")
    if not colon:
        dst = current if src in HEAD else src
    return HEADS.sub("", dst)


def git_config(listing: str, overrides: list[str] = ()) -> dict[str, list[str]]:
    """git's configuration as ``git config -z --list`` prints it (``key\\nvalue\\0`` entries), then the ``-c
    key=value`` of the push's own command (``overrides``, read last as git reads them): {key: [values, in order]}, the
    section and the variable lowercased, a subsection (a remote's or a branch's name) kept as it is."""
    out: dict[str, list[str]] = {}
    entries = [e.partition("\n") for e in listing.split("\0") if e]
    entries += [(o.partition("=")[0], "", o.partition("=")[2] if "=" in o else "true") for o in overrides]
    for key, _, value in entries:
        section, dot, rest = key.partition(".")
        sub, _, var = rest.rpartition(".")
        if dot and var:
            out.setdefault(".".join(p for p in (section.lower(), sub, var.lower()) if p), []).append(value)
    return out


def last(conf: dict[str, list[str]], key: str) -> str:
    """The value git reads for a single-valued ``key`` of git_config's dict: its last, else ''."""
    return (conf.get(key) or [""])[-1].strip()


def truthy(value: str) -> bool:
    """git's boolean: true, yes, on, 1 (a key given with no value is true too, git_config reads it 'true')."""
    return value.strip().lower() in ("true", "yes", "on", "1")


def default_remote(conf: dict[str, list[str]], current: str) -> str:
    """The remote a push that names none goes to: the current branch's pushRemote, remote.pushDefault, the branch's
    remote, else origin."""
    return (last(conf, f"branch.{current}.pushremote") or last(conf, "remote.pushdefault")
            or last(conf, f"branch.{current}.remote") or "origin")


def default_refspecs(conf: dict[str, list[str]], remote: str, current: str) -> list[str]:
    """What a push that names no refspec sends to ``remote``: its ``remote.<name>.push`` refspecs, else by
    ``push.default``: ``matching`` every branch both sides have (``:``), ``upstream`` (or ``tracking``) the current
    branch to its upstream (``branch.<name>.merge``), ``nothing`` nothing, ``current`` and ``simple`` (git's default)
    the current branch to its own name. No branch checked out sends nothing (git refuses the push)."""
    if conf.get(f"remote.{remote}.push"):
        return list(conf[f"remote.{remote}.push"])
    mode = last(conf, "push.default").lower() or "simple"
    if mode == "nothing":
        return []
    if mode == "matching":
        return [":"]
    if not current or current == "HEAD":
        return []
    if mode in ("upstream", "tracking"):
        return [f"{current}:{last(conf, f'branch.{current}.merge') or current}"]
    return [current]


def _wildcard(refspec: str) -> bool:
    """Whether a refspec with ``*`` writes main or master: its destination pattern (its source's when it has no
    destination), refs/heads/ or heads/ dropped, matches one of them."""
    src, colon, dst = refspec.lstrip("+").partition(":")
    pattern = HEADS.sub("", dst if colon else src)
    if not HEADS.match(dst if colon else src) and "/" in pattern and not pattern.startswith("*"):
        return False   # refs/tags/*, refs/remotes/*: not a branch
    rx = re.compile("^" + ".*".join(re.escape(p) for p in pattern.split("*")) + "$")
    return any(rx.match(b) for b in BRANCHES)


def push_refusal(refspecs: list[str], flags: set[str], current: str = "") -> tuple[str, str] | None:
    """(check, what) when a push breaks the floor: ``force`` (a forced push), else ``main`` (a push to main or
    master); ``refspecs`` are what the push sends (the guard gives the default's when the command names none,
    default_refspecs), ``current`` the branch checked out (needs_current), the one HEAD, @ or no refspec sends. A
    negative refspec (``^x``) sends nothing."""
    flags = {long_option(f) for f in flags}
    refspecs = [r for r in refspecs if not r.startswith("^")]
    force = forced(refspecs, flags)
    if force:
        return "force", f"a forced push ({force})"
    if flags & set(EVERY_BRANCH):
        return "main", "a push of every branch, main included"
    every = next((r for r in refspecs if r.lstrip("+") == ":" or ("*" in r and _wildcard(r))), "")
    if every:
        return "main", f"a push of every matching branch ({every}), main included"
    for spec, target in _targets(refspecs, flags, current):
        if target in BRANCHES:
            deleting = bool(flags & set(DELETE)) or spec.startswith(":")
            return "main", f"a {'deletion' if deleting else 'push'} of {target}"
    return None


def _targets(refspecs: list[str], flags: set[str], current: str) -> list[tuple[str, str]]:
    """(refspec, remote branch) for each branch a push writes: its refspecs' destinations, else the current branch
    (none for a push that sends no default: a deletion, --tags alone)."""
    if refspecs:
        return [(r, _destination(r, current)) for r in refspecs]
    return [] if flags & NO_DEFAULT else [("", current)]
