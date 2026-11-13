"""The locked floor (wi-brain-unadopted-floor; spec-brain-one-brain 4.8, the owner's R21): the few rules no level ever
overrides, and the guard's refusals that hold them.

- **A locked rule** is a line of the owner's rules (config.json ``rules``) that carries the marker ``<!-- lock -->``
  (or ``<!-- lock: ID -->``, the decision that locked it), an HTML comment that Markdown does not show.
  :func:`locked` returns those lines without the marker. A machine or a project that gets only the floor
  (``floor.only``) is injected these lines alone (inject-rules.sh), and its guard applies only the floor's refusals.
- **The floor's refusals** (brain.guards, guard ``floor``): a ``git push`` to ``main`` or ``master`` (a refspec's
  destination, ``--all``, ``--mirror``, the current branch when no refspec names one, a deletion of it) is check
  ``main``; a forced push (``--force``, ``-f`` in a group of short options, ``--force-with-lease``,
  ``--force-if-includes``, ``--mirror``, a refspec starting with ``+``) is check ``force``. A secret in a commit is
  the secrets guard's already. They run under config.json ``floor.refuse: true`` (off by default: refusals this
  release adds) or ``floor.only: true``; ``BRAIN_GUARD_ALLOW=floor`` (or ``floor:main``, ``floor:force``) lifts them,
  the owner's.
- **Floor only** (config.json ``floor.only: true``): the machine gets the floor and nothing else: only the locked
  rules are injected, with one line naming why; the guard runs only the floor's refusals and the secrets check; the
  memory notes are not synced, either way. How a machine or a project enters it on its own (a machine with no anchor
  in the owner's brain, a project until its merge phase) waits on the owner's answer; meanwhile the owner sets it.

Standard library only: the guard hook reads it.
"""

from __future__ import annotations

import re

LOCK = re.compile(r"\s*<!--\s*lock(?::\s*([\w.-]+))?\s*-->")
BRANCHES = ("main", "master")   # what no session pushes to (the owner merges by PR)
FORCE_FLAGS = ("--force", "--force-with-lease", "--force-if-includes", "--mirror")
ONLY_LINE = ("Floor only (config.json floor.only): this machine gets the locked rules alone, until it is adopted; "
             "the guard applies only the floor's refusals, and the memory notes are not synced.")


def locked(text: str) -> list[str]:
    """The lines of ``text`` that carry the lock marker, the marker taken out, in their order."""
    return [LOCK.sub("", line).rstrip() for line in text.splitlines() if LOCK.search(line)]


def settings(data: dict | None) -> dict:
    """config.json's ``floor``: {refuse, only}, each a bool (anything else is false)."""
    section = data.get("floor") if isinstance(data, dict) else None
    section = section if isinstance(section, dict) else {}
    return {"refuse": section.get("refuse") is True, "only": section.get("only") is True}


def _flags_force(flags: set[str]) -> str:
    """The flag that forces a push, else ''."""
    for f in flags:
        if f in FORCE_FLAGS:
            return f
        if re.fullmatch(r"-[A-Za-z]*f[A-Za-z]*", f) and not f.startswith("--"):
            return f
    return ""


def _destination(refspec: str) -> str:
    """The branch a refspec writes on the remote: SRC:DST's DST, else its SRC; refs/heads/ dropped."""
    dst = refspec.lstrip("+").split(":", 1)[-1]
    return re.sub(r"^refs/heads/", "", dst)


def push_refusal(refspecs: list[str], flags: set[str], current: str) -> tuple[str, str] | None:
    """(check, what) when a push breaks the floor: ``force`` (a forced push), else ``main`` (a push to main or
    master); ``current`` is the branch checked out, the one a push with no refspec sends."""
    force = _flags_force(flags) or next((r for r in refspecs if r.startswith("+")), "")
    if force:
        return "force", f"a forced push ({force})"
    if flags & {"--all", "--branches"}:
        return "main", "a push of every branch, main included"
    deleting = bool(flags & {"--delete", "-d"}) or any(r.startswith(":") for r in refspecs)
    hit = next((t for t in _targets(refspecs, flags, current) if t in BRANCHES), "")
    return ("main", f"a {'deletion' if deleting else 'push'} of {hit}") if hit else None


def _targets(refspecs: list[str], flags: set[str], current: str) -> list[str]:
    """The remote branches a push writes: its refspecs' destinations, else the current branch (none for a deletion
    with no refspec, or for --tags alone, which sends the tags only)."""
    if refspecs:
        return [_destination(r) for r in refspecs]
    return [] if flags & {"--delete", "-d", "--tags"} else [current]
