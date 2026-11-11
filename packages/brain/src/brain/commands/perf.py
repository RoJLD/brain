"""``brain perf``: the slowest steps, trends, regressions and time lost per week, from the ledger."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import perf

ORDER = 450   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 500   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain perf [--project P] [--since 28d|4w|DATE] [--task TEXT] [--top N] [--from PATH]... [--json]
                 the slowest steps, the trends, the regressions after a change and the time lost per week
  brain perf --usage [--since 28d] [--top N] [--json]
                 command adoption: each command's runs (by a session, otherwise), the never run, the hand reads and
                 edits a command answers, the have features never run; each gap's proposal (brain.adoption)
"""


def register(sub, ctx) -> None:
    pf = sub.add_parser("perf", help="the slowest steps, trends, regressions and time lost per week, from the ledger")
    pf.add_argument("--project", default=argparse.SUPPRESS, help="only this project (default: every one)")
    pf.add_argument("--since", help=f"Nd, Nw, YYYY-MM-DD or an ISO time (default: {perf.SINCE_DAYS}d)")
    pf.add_argument("--task", help="only the tasks that contain this text (any case)")
    pf.add_argument("--top", type=int, default=perf.TOP, help=f"rows of the slowest steps and trends (default "
                                                              f"{perf.TOP}; 0: all)")
    pf.add_argument("--from", dest="sources", action="append", metavar="PATH",
                    help="a JSONL file or a folder of them to read instead of the ledger (repeatable)")
    pf.add_argument("--engine", action="store_true", help="the engine's own runs instead (every brain command and "
                                                          "hook, brain.selftime): its slow steps, regressions, hook time "
                                                          "per week and the errors it caught")
    pf.add_argument("--usage", action="store_true", help="command adoption instead: the CLI registry crossed with "
                                                         "the engine's exec ledger, the transcripts and the features "
                                                         "(brain.adoption)")
    pf.add_argument("--json", action="store_true")


def early(args) -> int:
    if args.usage:
        if args.engine or args.sources or args.task or args.project:
            print("brain perf: --usage reads the engine's ledger and this machine's transcripts, not with --engine, "
                  "--from, --task or --project", file=sys.stderr)
            return 2
        from .. import adoption
        return adoption.main(since=args.since, top=args.top, as_json=args.json,
                             root=Path(args.root).resolve() if args.root else None)
    return perf.main(project=args.project, since=args.since, task=args.task, top=args.top, sources=args.sources,
                     as_json=args.json, engine=args.engine)
