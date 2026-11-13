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


def locked(text: str) -> list[str]:
    """The lines of ``text`` that carry the lock marker, the marker taken out, in their order (lines split on LF, a
    CR dropped, as inject-rules.sh reads them)."""
    return [LOCK.sub("", line).rstrip(" \t\n\r\f\v") for line in text.replace("\r", "").split("\n")
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


def push_refusal(refspecs: list[str], flags: set[str], current: str = "") -> tuple[str, str] | None:
    """(check, what) when a push breaks the floor: ``force`` (a forced push), else ``main`` (a push to main or
    master); ``refspecs`` are what the push sends (the guard gives the default's when the command names none),
    ``current`` the branch checked out (needs_current), the one HEAD, @ or no refspec sends."""
    flags = {long_option(f) for f in flags}
    force = forced(refspecs, flags)
    if force:
        return "force", f"a forced push ({force})"
    if flags & set(EVERY_BRANCH):
        return "main", "a push of every branch, main included"
    every = next((r for r in refspecs if r.lstrip("+") == ":" or "*" in r), "")
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
