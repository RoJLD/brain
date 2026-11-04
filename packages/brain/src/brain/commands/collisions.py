"""``brain collisions``: the files each open branch and worktree touches, crossed with the startable items' predicted
surface: who can start now, who waits on whom.
"""

from __future__ import annotations

import json
from pathlib import Path

from ._common import _scope

ORDER = 510   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 170   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain collisions [--all] [--json]   at zero token: the files each open branch and worktree of the project's repos
                        touches (against the default branch, uncommitted changes included), crossed with each
                        startable item's predicted surface (its features' CodeRefs, its module, the files it names):
                        the items that can start now, and those that wait on a branch (and its session)
"""


def cmd_collisions(args, root: Path) -> int:
    """brain collisions (brain.collisions): the project here or --project's, or --all."""
    from .. import collisions
    rep = collisions.report(_scope(args, root), frontier=args.frontier)
    print(json.dumps(rep.as_dict(), indent=2) if args.json else "\n".join(collisions.render(rep)))
    return 0


def register(sub, ctx) -> None:
    co_ = sub.add_parser("collisions", help="the files each open branch and worktree touches, crossed with the "
                                            "startable items' predicted surface: who can start now, who waits on whom")
    co_.add_argument("--all", action="store_true", help="every project of the registry")
    co_.add_argument("--frontier", action="store_true", help="every startable item, not only the P0/P1 ones")
    co_.add_argument("--json", action="store_true")


run = cmd_collisions
