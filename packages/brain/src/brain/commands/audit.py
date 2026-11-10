"""``brain audit``: what misses the standard per repo and module, at zero token (brain.audit); --diff: the scout on a
change (brain.scout).
"""

from __future__ import annotations

from .. import audit, skew
from ._common import _whole, root_of

ORDER = 360   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 410   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain audit [--all] [--repo R]... [-v] [--json] [--trend [N]] [--fail-on P] [--write [--force]] [--items]
                 what misses the standard per repo and module (zero token): P0 false statements, P1 gaps on
                 production paths; --write: another engine than config.json engine.pin writes nothing
  brain audit --diff [BASE|A..B] [--repo-dir D] [--store DIR] [--limit N]   the scout: what the modules a change
                 touches miss (NEW, LEFT, DEFER); exit 1 when something is to fix in the PR
"""


def register(sub, ctx) -> None:
    au = sub.add_parser("audit", help="what misses the standard per repo and module, at zero token (brain.audit); "
                                      "--diff: the scout on a change (brain.scout)")
    au.add_argument("--all", action="store_true", help="every registered project, then the milestone line")
    au.add_argument("--repo", action="append", help="only this repo of the project (repeatable)")
    au.add_argument("-v", "--verbose", action="store_true", help="every finding, info included")
    au.add_argument("--json", action="store_true", help="stable keys, no timestamp")
    au.add_argument("--trend", nargs="?", type=int, const=5, default=0, metavar="N",
                    help="also re-measure the last N completed ISO weeks at their end commit (default 5)")
    au.add_argument("--fail-on", choices=list(audit.SEVERITIES), help="exit 1 on a finding at this severity or above")
    au.add_argument("--write", action="store_true", help=f"write {audit.VIEW} (one project, from a worktree)")
    au.add_argument("--force", action="store_true", help="--write even when the running engine is not config.json "
                                                         "engine.pin")
    au.add_argument("--items", action="store_true", help="one debt item per repo with debt, priority proposed "
                                                         "(one project, from a worktree)")
    au.add_argument("--diff", nargs="?", const="", default=None, metavar="BASE|A..B",
                    help="the scout: from merge-base(HEAD, the default branch, or BASE) to the working tree, or the "
                         "commits A..B")
    au.add_argument("--repo-dir", metavar="D", help="--diff: the repo changed (default: the current folder)")
    au.add_argument("--store", dest="audit_store", metavar="DIR",
                    help="--diff: a code store in a worktree (a cross-repo change)")
    au.add_argument("--limit", type=_whole, metavar="N",
                    help="--diff: LEFT units to fix in this PR (default: scout_limit, 3)")
    au.add_argument("--pr-body", metavar="FILE", help="--diff: the PR body ('-' for stdin), where the structure "
                                                      "signals read Root cause: and Justified: lines (the range's "
                                                      "commit messages are read too)")


def early(args) -> int:
    """Its repos may have no graph store: before find_root. --write: another engine than config.json engine.pin
    writes nothing, before the measure (brain.skew)."""
    root = root_of(args)
    if args.write and skew.refuse(root, "audit --write", args.force, f"the committed {audit.VIEW}"):
        return 1
    return audit.main(args, root)
