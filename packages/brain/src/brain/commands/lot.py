"""``brain lot check``: whether a finished lot's session can be archived: its worktrees clean, its branches merged
or kept and pushed, what to remove listed (brain.lotcheck); read only.
"""

from __future__ import annotations

import json
import os
import sys

from .. import lotcheck

ORDER = 292   # its place in brain --help's list of commands (brain.commands): after tidy
USAGE_ORDER = 141   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain lot check [SESSION] [--branch B]... [--keep B]... [--repo-dir D]... [--scratch GLOB]... [--lot NAME]
                 [--offline] [--json]   a finished lot (a session a coordinator started; default: this one) read from
                 the desktop app's file of it: each worktree on its branches clean, each branch merged (its PR, or the
                 default branch holds it) or kept on purpose, and pushed; « ready to archive » (exit 0) and what to
                 remove (worktrees, branches, the scratch folders GLOB names, {lot}: the lot's name), else what is left
                 (exit 1); 2 when the session is not found. Read only: the archive stays the app's tool
"""


def _ids(values) -> list[str]:
    return [v.strip() for x in values or [] for v in str(x).split(",") if v.strip()]


def early(args) -> int:
    """``brain lot check``: the lot's state, read only (brain.lotcheck); no brain root needed."""
    session = args.session or os.environ.get("CLAUDE_CODE_HOST_SESSION_ID", "")
    if not session:
        print("brain lot check: which session? (SESSION, or run it in the session itself)", file=sys.stderr)
        return 2
    try:
        rep = lotcheck.check(session, branches=_ids(args.branch), keep=_ids(args.keep), repo_dirs=args.repo_dir or [],
                             scratch=args.scratch or [], lot=args.lot or "", offline=args.offline)
    except lotcheck.LotError as exc:
        print(f"brain lot check: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(rep.to_json(), indent=1, ensure_ascii=False) if args.json else "\n".join(lotcheck.lines(rep)))
    return 0 if rep.ready else 1


def register(sub, ctx) -> None:
    lt = sub.add_parser("lot", help="a lot's state: brain lot check SESSION says whether it can be archived "
                                    "(read only)").add_subparsers(dest="lot_cmd", required=True)
    ck = lt.add_parser("check", help="worktrees clean, branches merged or kept and pushed, what to remove; "
                                     "« ready to archive » or what is left")
    ck.add_argument("session", nargs="?", help="the session's local_ id (default: this session, "
                                               "$CLAUDE_CODE_HOST_SESSION_ID)")
    ck.add_argument("--branch", action="append", help="a branch of the lot the app did not record (repeatable, or "
                                                      "comma-separated)")
    ck.add_argument("--keep", action="append", help="a branch kept on purpose, unmerged (repeatable)")
    ck.add_argument("--repo-dir", action="append", help="a repo to read besides those the session touched")
    ck.add_argument("--scratch", action="append", metavar="GLOB",
                    help="scratch folders to list for removal ({lot}: the lot's name; repeatable)")
    ck.add_argument("--lot", help="the lot's name (default: the session's name)")
    ck.add_argument("--offline", action="store_true", help="the PR states the app last saw, no gh call")
    ck.add_argument("--json", action="store_true", help="the report as data")

