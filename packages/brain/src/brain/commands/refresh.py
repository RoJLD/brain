"""``brain refresh``: sync then check for the project's stores, or every registered project's; with --all, or in a
brain's own root, the registry check of check --all too. First, while config.json ``tidy.auto`` is on, the
merged-and-clean part of brain tidy's plan of their repos is applied (brain.tidy.auto, wi-brain-tidy-at-close).
Before it, the owner's engine clone is fast-forwarded when it is on main and clean (brain.engineclone,
wi-brain-clone-autopull).
"""

from __future__ import annotations

from pathlib import Path

from .. import engineclone, skew, tidy
from ._common import _scope
from ._stores import _each_store, _merge_marks

ORDER = 280   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 130   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain refresh [--all] [--offline] [--no-tidy] [--no-clone]   sync, then check, for this project's stores or every
                        registered project's (--all: and the registry and the ids, as check --all); first, the
                        owner's engine clone (config.json engine.clone, else the registry's checkout of engine.repo)
                        fast-forwarded with git pull --ff-only when it is on main, clean and in no merge or rebase,
                        else said and left as it is: never a switch, commit, reset or stash (--offline or
                        --no-clone skip it); then, while config.json
                        tidy.auto is on (the default), the merged-and-clean part of brain tidy's plan of their repos
                        is applied (the stale worktrees on a merged branch, the merged local branches, the worktrees
                        whose folder is gone; never origin's, an unmerged branch, a dirty, locked or leased worktree
                        or the current folder; --no-tidy skips it); check and refresh end with brain tidy's line when
                        its repos still hold stale worktrees or merged branches; a main checkout on main or master is
                        only checked (--on-main: written), where a stale view is a warning, an error under config.json
                        views.strict (brain views --write, from a worktree at its tip, is the one writer)
"""


def _tidy(args, root: Path, scope) -> None:
    """The merged-and-clean part of brain tidy's plan of each project's repos, applied (config.json tidy.auto, unless
    --no-tidy); one line per step, never a failure of the refresh."""
    if args.no_tidy or not tidy.auto_on(root):
        return
    for p in scope:
        for line in tidy.auto(p):
            print(line if line.startswith("warning:") else f"tidy: {line}")


def _clone(args, root: Path) -> None:
    """The owner's engine clone fast-forwarded when it is on main and clean (brain.engineclone), one line; never a
    failure of the refresh. Skipped with --offline (a network read) or --no-clone."""
    if args.offline or args.no_clone:
        return
    said = engineclone.refresh(root).said()
    if said:
        print(said)


def cmd_refresh(args, root: Path) -> int:
    """the engine clone's fast-forward, tidy's merged-and-clean part, then sync --write, the records and queue views, kanban --write, then check, for
    each store of each project in scope. A main checkout on main or master is only checked (its generated files are
    refreshed from a worktree), unless --on-main. --all ends with the registry and the ids (check_registry). Once it
    passes, the views the merge driver kept from one side here are regenerated: their marks are cleared."""
    if skew.refuse(root, "refresh", args.force):   # another engine than config.json engine.pin: nothing written
        return 1
    scope = _scope(args, root, root_shared=True)
    _clone(args, root)
    _tidy(args, root, scope)
    rc = _each_store(args, root, sync=True, check=True, scope=scope)
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
    rf.add_argument("--no-tidy", action="store_true",
                    help="skip the merged-and-clean part of brain tidy applied first (config.json tidy.auto)")
    rf.add_argument("--no-clone", action="store_true",
                    help="leave the owner's engine clone as it is (by default fast-forwarded when on main and clean)")


run = cmd_refresh
