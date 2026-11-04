"""``brain sync``: research_graph sync --write, records graph, queue view, the features' statuses from merged PRs and
FEATURES.md, kanban --write.
"""

from __future__ import annotations

from pathlib import Path

from .. import skew
from ._common import _store
from ._stores import _each_store, _sync_store

ORDER = 110   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 110   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain sync [--all] [--offline]   the ready proposed specs turned active (brain spec activate --write), then
                        research_graph sync --write, the records' graph view, the decision queue view,
                        the links graph (Doc, Test and Workflow nodes, documented_in, tested_by and runs, brain.links),
                        the features' statuses from merged PRs (gh; not with --offline) and FEATURES.md, kanban --write
"""


def cmd_sync(args, root: Path) -> int:
    if skew.refuse(root, "sync", args.force):   # another engine than config.json engine.pin: nothing written
        return 1
    if args.all:
        return _each_store(args, root, sync=True, check=False)
    return _sync_store(args, root, _store(args, root))


def register(sub, ctx) -> None:
    sy = sub.add_parser("sync", help="research_graph sync --write, records graph, queue view, the features' "
                                     "statuses from merged PRs and FEATURES.md, kanban --write")
    sy.add_argument("--offline", action="store_true", help="no gh call (the features' statuses are not read)")
    sy.add_argument("--all", action="store_true", help="every project of the registry (a main checkout on main or "
                                                       "master is not written)")
    sy.add_argument("--force", action="store_true", help="write even when the running engine is not config.json "
                                                         "engine.pin (brain check says how they differ)")


run = cmd_sync
