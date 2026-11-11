"""``brain session-archive``: the agents' transcripts, scanned, filtered and sealed into the spool
(brain.sessionarchive)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import config, sessionarchive

ORDER = 253   # its place in brain --help's list of commands (brain.commands): after spool
USAGE_ORDER = 293   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain session-archive run [--dry-run] [--max N] [--json]   opt-in (config.json session_archive.enabled): the
                 transcripts quiet for 2 h and changed since archived, each row a residency filter matches dropped
                 (session_archive.resident), scanned by the engine's patterns then gitleaks (absent: nothing
                 archived), sealed into the spool (store session-archive) and indexed by session record; --dry-run
                 lists what would be archived and dropped, seals nothing; exit 2 when refused
  brain session-archive status [--json]   on or off, gitleaks, the index's sessions and files, the last run
"""


def cmd_session_archive(args, root: Path) -> int:
    """``brain session-archive``: run, status. Exit 2 on a refusal (no gitleaks, a bad filter, the spool's or the
    index's refusal): nothing sealed then."""
    cfg = config.load(root)
    try:
        if args.sarch_cmd == "status":
            s = sessionarchive.status(cfg)
            print(json.dumps(s, indent=1, sort_keys=True) if args.json else "\n".join(sessionarchive.render_status(s)))
            return 0
        res = sessionarchive.run(cfg, dry_run=args.dry_run, max_files=args.max)
    except sessionarchive.ArchiveError as exc:
        print(f"brain session-archive {args.sarch_cmd}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=1, sort_keys=True) if args.json else "\n".join(sessionarchive.run_lines(res)))
    return 0


def _positive(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError("N is 1 or more")
    return n


def register(sub, ctx) -> None:
    sp = sub.add_parser("session-archive", help="the agents' transcripts, scanned (gitleaks), filtered and sealed "
                                                "into the spool, opt-in (brain.sessionarchive)"
                        ).add_subparsers(dest="sarch_cmd", required=True)
    pr = sp.add_parser("run", help="archive the quiet transcripts changed since their last archive")
    pr.add_argument("--dry-run", action="store_true", help="the plan and what would be dropped: nothing sealed")
    pr.add_argument("--max", type=_positive, default=None, metavar="N",
                    help="at most N transcripts this run (default session_archive.max_files, else 200)")
    pr.add_argument("--json", action="store_true", help="stable keys")
    ps = sp.add_parser("status", help="on or off, the scanner, the index, the last run")
    ps.add_argument("--json", action="store_true", help="stable keys")


run = cmd_session_archive
