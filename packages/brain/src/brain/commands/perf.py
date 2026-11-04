"""``brain perf``: the slowest steps, trends, regressions and time lost per week, from the ledger."""

from __future__ import annotations

import argparse

from .. import perf

ORDER = 450   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 500   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain perf [--project P] [--since 28d|4w|DATE] [--task TEXT] [--top N] [--from PATH]... [--json]
                 the slowest steps, the trends, the regressions after a change and the time lost per week
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
    pf.add_argument("--json", action="store_true")


def early(args) -> int:
    return perf.main(project=args.project, since=args.since, task=args.task, top=args.top, sources=args.sources,
                     as_json=args.json, engine=args.engine)
