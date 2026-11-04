"""``brain up``: start stacks and their dependencies, in dependency order; a healthy one is untouched, except a Compose
stack (docker compose up -d applies a changed compose file).
"""

from __future__ import annotations

from .. import projects, stacks
from ._common import root_of

ORDER = 320   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 420   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain up [STACK]... [--force]   start stacks after their dependencies, waiting for health; a healthy one is
                                  untouched, unless named with --force (its start command runs again) or a Compose
                                  stack (docker compose up -d always runs: it applies a changed compose file)
"""


def register(sub, ctx) -> None:
    sp = sub.add_parser("up", help="start stacks and their dependencies, in dependency order; a healthy one is "
                                   "untouched, except a Compose stack (docker compose up -d applies a changed compose "
                                   "file)")
    sp.add_argument("stacks", nargs="*", metavar="STACK")
    sp.add_argument("--force", action="store_true", help="run the named stacks' start command even when "
                    "healthy, to apply a changed configuration (docker compose up -d recreates what changed)")


def early(args) -> int:
    """Stack names are global: any project's registry."""
    root = root_of(args)
    if args.project:
        projects.get(args.project, root)  # an unknown project stops here
    return stacks.main(args.cmd, args.stacks, False, root, getattr(args, "force", False), project=args.project)
