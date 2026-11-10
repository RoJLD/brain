"""``brain refresh``: sync then check for the project's stores, or every registered project's; with --all, or in a
brain's own root, the registry check of check --all too.
"""

from __future__ import annotations

from pathlib import Path

from .. import skew
from ._stores import _each_store, _merge_marks

ORDER = 280   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 130   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain refresh [--all] [--offline]   sync, then check, for this project's stores or every registered project's (--all: and the
                        registry and the ids, as check --all); check and refresh end with brain tidy's line when its
                        repos hold stale worktrees or merged branches; a main checkout on main or master is only
                        checked (--on-main: written), where a stale view is a warning, an error under config.json
                        views.strict (brain views --write, from a worktree at its tip, is the one writer)
"""


def cmd_refresh(args, root: Path) -> int:
    """sync --write, the records and queue views, kanban --write, then check, for each store of each project in
    scope. A main checkout on main or master is only checked (its generated files are refreshed from a worktree),
    unless --on-main. --all ends with the registry and the ids (check_registry). Once it passes, the views the merge
    driver kept from one side here are regenerated: their marks are cleared."""
    if skew.refuse(root, "refresh", args.force):   # another engine than config.json engine.pin: nothing written
        return 1
    rc = _each_store(args, root, sync=True, check=True)
    if not rc:
        _merge_marks(root, "regenerated", clear=True)
    return rc


def register(sub, ctx) -> None:
    rf = sub.add_parser("refresh", help="sync then check for the project's stores, or every registered project's; "
                                        "with --all, or in a brain's own root, the registry check of check --all too")
    rf.add_argument("--offline", action="store_true", help="no gh call (the features' statuses are not read)")
    rf.add_argument("--all", action="store_true", help="every project of the registry")
    rf.add_argument("--force", action="store_true", help="write even when the running engine is not config.json "
                                                         "engine.pin")
    rf.add_argument("--on-main", action="store_true",
                    help="also write in a main checkout on main or master (by default it is only checked)")


run = cmd_refresh
