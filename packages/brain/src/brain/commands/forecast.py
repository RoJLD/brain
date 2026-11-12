"""``brain forecast``: when each milestone and the whole backlog will be done: p10-p90 from a Monte Carlo of futures,
under the honesty bar (zero token).
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import cost, forecast, usage
from ._common import _scope, _whole

ORDER = 180   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 530   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain forecast [--project P | --all] [--runs N] [--seed S] [--items] [--no-scan] [--json]   when each milestone
                 and the whole backlog will be done: a Monte Carlo of futures (a shared estimate error from the
                 backtests, a lognormal per item from its p25-p75, the capacity of past days, the proposals' keep rate,
                 the owner's answer and action delays, the gates written on the nodes (props.gate: calendar, count,
                 external, hardware, go_nogo; docs/gates.md), an event-queue scheduler by priority, order, then the
                 default score; an alert when an item's p80 passes its due date), p10-p90
                 under the honesty bar: uncalibrated until 5 reached milestones are judged, no date beyond 6 weeks,
                 none for a backlog that grows faster than it empties, the deferred items and the inflow apart; --items
                 per item p10 . p50 . p80 . p90; --json reproducible (seed, input digests, code version); every run
                 keeps <BRAIN_HOME>/forecast/<project>/latest.json (brain status --quick reads it)
"""


def cmd_forecast(args, root: Path) -> int:
    """brain forecast (brain.forecast): the project here or --project's, or each project with --all (each alone:
    the joint simulation is wi-brain-scope-rollups'); each run keeps latest.json."""
    if args.runs < 1:
        raise SystemExit("brain forecast: --runs needs one future at least")
    projs = _scope(args, root)
    led = cost.load(projs, root, refresh=not args.no_scan)
    now = usage.now_utc()
    out = []
    for p in projs:
        if not p.root.is_dir():
            continue
        try:
            res = forecast.forecast(p, cost.Ledger(led.rows, [p]) if len(projs) > 1 else led, now, runs=args.runs,
                                    seed=args.seed)
        except forecast.ForecastError as exc:
            print(f"brain forecast {p.name}: {exc}", file=sys.stderr)
            continue
        forecast.save(res)
        out.append(res)
    if args.json:
        print(forecast.as_json(out[0] if len(out) == 1 and not args.all else out))
    else:
        print("\n\n".join("\n".join(forecast.render(res, args.items)) for res in out))
    return 0 if out else 1


def register(sub, ctx) -> None:
    fo = sub.add_parser("forecast", help="when each milestone and the whole backlog will be done: p10-p90 from a Monte "
                                         "Carlo of futures, under the honesty bar (zero token)")
    fo.add_argument("--all", action="store_true", help="every registered project, each alone")
    fo.add_argument("--runs", type=_whole, default=forecast.RUNS, help=f"futures (default {forecast.RUNS})")
    fo.add_argument("--seed", type=int, default=forecast.SEED, help=f"the draws' seed (default {forecast.SEED}): the "
                                                                    "same inputs and seed give the same numbers")
    fo.add_argument("--items", action="store_true", help="each item's p10 . p50 . p80 . p90, and why the others are "
                                                         "not dated")
    fo.add_argument("--no-scan", action="store_true", help="read the token ledger as it is, without scanning the "
                                                          "transcripts that changed")
    fo.add_argument("--json", action="store_true", help="the result with its seed, input digests and code version")


run = cmd_forecast
