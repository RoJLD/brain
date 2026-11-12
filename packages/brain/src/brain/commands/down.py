"""``brain down``: stop stacks (every one with a stop command when none is named), reverse order."""

from __future__ import annotations

from .. import projects, stacks
from ._common import root_of

ORDER = 330   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 430   # its usage lines' place in brain --help's epilog
RUNS_VIA = {   # brain perf --usage: how a subcommand that may never run from the CLI is reached (brain.adoption)
    "down": "on demand: stops a watched stack (brain up starts it)",
}
USAGE = """\
  brain down [STACK]...     stop stacks, in reverse dependency order (up and down --project P: P's stacks)
"""


def register(sub, ctx) -> None:
    sp = sub.add_parser("down", help="stop stacks (every one with a stop command when none is named), reverse order")
    sp.add_argument("stacks", nargs="*", metavar="STACK")


def early(args) -> int:
    """Stack names are global: any project's registry."""
    root = root_of(args)
    if args.project:
        projects.get(args.project, root)  # an unknown project stops here
    return stacks.main(args.cmd, args.stacks, False, root, getattr(args, "force", False), project=args.project)
