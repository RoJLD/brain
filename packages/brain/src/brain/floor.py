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

import re

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
# The variables no command sets while the floor is on, in any form (a prefix NAME=, export, declare, printf -v, read,
# env, PowerShell's $env: and Set-Item env:, SetEnvironmentVariable): git's own (its configuration, repository and
# programs), what chooses git's global configuration (HOME, XDG_CONFIG_HOME), what bash reads before a script (BASH_ENV,
# ENV, SHELLOPTS, BASHOPTS), PATH, and the Brain's and Claude Code's own.
WATCHED_VARS = r"GIT_\w+|HOME|USERPROFILE|XDG_CONFIG_HOME|BASH_ENV|ENV|SHELLOPTS|BASHOPTS|PATH|BRAIN_\w+|CLAUDE_\w+"
_START = r"(?:^|(?<=[\s;&|(]))"
ENV_ASSIGN = re.compile(
    rf"{_START}(?:{WATCHED_VARS})\+?=|"                                                   # NAME=, NAME+= (bash, cmd's set)
    rf"\b(?:export|declare|typeset|readonly|read)\b[^;&|\n]*?(?<![\w${{])(?:{WATCHED_VARS})\b|"
    rf"\bprintf\s+-v\s*(?:{WATCHED_VARS})\b|"
    rf"(?i:\$\{{?env:(?:{WATCHED_VARS})\}}?\s*[+-]?=)|"                                  # $env:X = , ${env:X} =
    rf"(?i:\b(?:set-item|new-item|set-content|remove-item|si|ni|sc|ri)\b[^;|\n]*\benv:(?:{WATCHED_VARS})\b)|"
    rf"(?i:SetEnvironmentVariable\s*\(\s*(?:{WATCHED_VARS})\s*,)")
# An assignment whose name the guard cannot read (a variable, a call): refused while the floor is on.
ENV_DYNAMIC = re.compile(r"\b(?:export|declare|typeset|printf\s+-v)\s+(?:-\w+\s+)*[^\s;=]*[$(`]|"
                         r"(?i:\benv:[^\s;=]*[$(]|\$\{env:[^}]*[$(])")
# git's global options a command may give while the floor is on (-c and --config-env are refused on their own).
GIT_GLOBAL_OK = {"-C", "--no-pager", "-P", "--paginate", "-p", "--no-optional-locks", "--literal-pathspecs",
                 "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs", "--no-advice", "-c", "--config-env"}
# git's own configuration files: an alias, an include or a mirror written there changes what a push does.
GIT_CONFIG_FILES = re.compile(r"(?i)(?:^|[\\/])(?:\.gitconfig|\.git[\\/]config(?:\.worktree)?|git[\\/]config)$")
# The configuration keys a session does not set while the floor is on (git config): aliases, includes, remotes,
# push's own keys, URL rewrites.
PUSH_KEYS = re.compile(r"(?i)^(?:alias\..+|include(?:if\..+)?\.path|remote\..+|push\..+|url\..+)$")
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
