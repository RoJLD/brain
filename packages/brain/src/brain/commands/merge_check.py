"""``brain merge-check``: after a merge of main into a branch: nothing of a fresh main lost (logs, edge files,
CHANGELOGs, node ids); exit 1 when lost or behind.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import resume
from ..inventory import AuditError

ORDER = 500   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 160   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain merge-check [--base REF] [--no-fetch] [--worktree] [--path P]... [--repo DIR] [--json]   after a merge of
                        main into a branch: a remote base fetched again, nothing main brought since the merge base
                        lost (its lines in the journals, decision logs, edge files and CHANGELOGs, as content; the
                        fields it changed on the graph's nodes; its nodes, unless the branch removed them); exit 1
                        when the branch is behind the base or lost something
"""


def cmd_merge_check(args) -> int:
    """brain merge-check (brain.mergecheck): the repo here or --repo's, the registered project's files."""
    from .. import mergecheck
    try:
        top = Path(git_top(Path(args.repo or ".").resolve()))
        try:
            project = resume.project_for(top)
        except (OSError, ValueError):
            project = None
        r = mergecheck.check(top, project if project and project.registered else None, args.base or "",
                             fetch=not args.no_fetch, worktree=args.worktree, extra=args.path)
    except AuditError as exc:
        print(f"brain merge-check: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=1) if args.json else "\n".join(mergecheck.render(r)))
    return 1 if mergecheck.failed(r) else 0


def git_top(d: Path) -> str:
    from ..inventory import git
    return git(d, "rev-parse", "--show-toplevel").strip()


def register(sub, ctx) -> None:
    mc = sub.add_parser("merge-check", help="after a merge of main into a branch: nothing of a fresh main lost (logs, "
                                            "edge files, CHANGELOGs, node ids); exit 1 when lost or behind")
    mc.add_argument("--base", help="the base (default: origin's default branch)")
    mc.add_argument("--no-fetch", action="store_true", help="the base as last fetched")
    mc.add_argument("--worktree", action="store_true", help="the working tree, not HEAD (a resolution not committed)")
    mc.add_argument("--path", action="append", help="one more file whose lines must all stay (repeatable)")
    mc.add_argument("--repo", help="the repo (default: the one here)")
    mc.add_argument("--json", action="store_true")


def early(args) -> int:
    """Any git repo; the registered project's files when it is one."""
    return cmd_merge_check(args)
