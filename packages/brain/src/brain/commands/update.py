"""``brain update``: a newer engine: the latest tag of config.json engine.repo, its CHANGELOG and the plan (install it
into the brain's venv, swap the launcher, the pin to move by PR); installed on the owner's yes only (y, or --yes),
never from a Claude Code session.
"""

from __future__ import annotations

from pathlib import Path

from .. import detail, update
from ._common import root_of

ORDER = 150   # its place in brain --help's list of commands (brain.commands)


def cmd_update(args, root: Path | None) -> int:
    """brain update (brain.update): the latest tag of the engine's repo read now (the cache refreshed), its CHANGELOG
    and the plan; --check stops there; else installed on the owner's yes (y in a terminal, or --yes), refused in a
    Claude Code session's shell (CLAUDECODE), like the cockpit's actions."""
    return update.main(root, check_only=args.check, yes=args.yes, as_json=args.json, refused=detail.refused())


def register(sub, ctx) -> None:
    who = ctx.who
    up = sub.add_parser("update", help=f"a newer engine: the latest tag of config.json engine.repo, its CHANGELOG and "
                                       f"the plan (install it into the brain's venv, swap the launcher, the pin to "
                                       f"move by PR); installed on {who}'s yes only (y, or --yes), never from a "
                                       "Claude Code session")
    up.add_argument("--check", action="store_true", help="print the plan and exit: install nothing")
    up.add_argument("--yes", action="store_true", help="install without asking (the owner's own terminal)")
    up.add_argument("--json", action="store_true", help="the plan's data (stable keys)")


def early(args) -> int:
    """The engine of this machine: a brain without a graph store updates too."""
    return cmd_update(args, root_of(args))
