"""``brain update``: a newer engine: the latest tag of config.json engine.repo, its CHANGELOG and the plan (install it
into the brain's venv, swap the launcher, then the pin: written, committed and brain sync run for a brain without an
installer of its own, by a reviewed PR for one that declares engine.installer, COMPAT-5); run on the owner's yes
only (y, or --yes), never from a Claude Code session.
"""

from __future__ import annotations

from pathlib import Path

from .. import detail, update
from ._common import root_of

ORDER = 150   # its place in brain --help's list of commands (brain.commands)


def cmd_update(args, root: Path | None) -> int:
    """brain update (brain.update): the latest tag of the engine's repo read now (the cache refreshed), its CHANGELOG
    and the plan; --check stops there; else run on the owner's yes (y in a terminal, or --yes): the install, and the
    pin moved and committed then brain sync for a brain without an installer of its own; refused in a Claude Code
    session's shell (CLAUDECODE), like the cockpit's actions."""
    return update.main(root, check_only=args.check, yes=args.yes, as_json=args.json, refused=detail.refused())


def register(sub, ctx) -> None:
    who = ctx.who
    about = (f"a newer engine: the latest tag of config.json engine.repo, its CHANGELOG and "
             f"the plan (install it into the brain's venv, swap the launcher; then "
             f"config.json engine.pin: written, committed and brain sync run when the "
             f"brain declares no engine.installer, else moved by a reviewed PR); run on "
             f"{who}'s yes only (y, or --yes), never from a Claude Code session: run it "
             "in your own terminal")
    up = sub.add_parser("update", help=about, description=about)
    up.add_argument("--check", action="store_true", help="print the plan and exit: install nothing, move no pin")
    up.add_argument("--yes", action="store_true", help="run the plan without asking: install, and move the pin of a "
                                                       "brain without an installer (the owner's own terminal)")
    up.add_argument("--json", action="store_true", help="the plan's data (stable keys)")


def early(args) -> int:
    """The engine of this machine: a brain without a graph store updates too."""
    return cmd_update(args, root_of(args))
