"""``brain cost``: estimate an item from the finished ones, review actual against estimate and budget, audit the
estimates (zero token).
"""

from __future__ import annotations

from pathlib import Path

from .. import cost, forecast, usage
from ._common import _scope, _text, _when, _whole

ORDER = 170   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 520   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain cost estimate ITEM|TEXT|@FILE|- [--class trivial|standard|strategic] [--record] [--json]   cost, output,
                 context peak, active time and sessions (median, p25-p75) from the finished items most alike, times
                 the class's calibration; --record writes props.cost_estimate on the item
  brain cost review [ITEM] [--since WHEN] [--until WHEN] [--record] [--json]   actual against the recorded (else
                 backtest) estimate and the brief's budget, and the token-free signals that explain the gap;
                 --record writes props.cost_review
  brain cost audit [--since WHEN] [--until WHEN] [--top N] [--write] [--json]   the window's estimates off by more
                 than x1.5 and why, the calibration per class, the costliest sessions, the script candidates;
                 --write: <BRAIN_HOME>/usage/<project>/audit-<since>_<until>.md, and the week's forecast snapshot
                 <BRAIN_HOME>/forecast/<project>/<day>.json (the Monday task's command)
"""


def cmd_cost(args, root: Path) -> int:
    """brain cost estimate|review|audit (brain.cost): the project here or --project's items and sessions."""
    projs = _scope(args, root)
    led = cost.load(projs, root)
    today = usage.now_utc().date().isoformat()
    if args.cost_cmd == "estimate":
        target = cost.target_of(led, _text(args.target), args.task_class)
        est = cost.estimate(led, target, today)
        if args.record:
            if target.get("id") != args.target.strip():
                raise SystemExit("brain: --record needs an item id as the target")
            cost.record(target.get("store"), target["id"], "cost_estimate", cost.estimate_text(est))
        print(cost.as_json(est) if args.json else "\n".join(cost.render_estimate(est) + (
            [f"recorded on {target['id']} (props.cost_estimate); then brain refresh"] if args.record else [])))
        return 0
    since, until = _when(args.since), _when(args.until)
    if args.cost_cmd == "review":
        if args.item and args.item not in led.items:
            raise SystemExit(f"brain: {args.item}: no such item in {', '.join(p.name for p in projs)}")
        ids = [args.item] if args.item else [a["id"] for a in cost.history(led) if a["done_day"] >= since
                                             and (not until or a["done_day"] < until)]
        reviews = [cost.review(led, i) for i in ids]
        if args.record:
            for rv in reviews:
                cost.record(led.items[rv["item"]["id"]].store, rv["item"]["id"], "cost_review",
                            cost.review_text(rv, today))
        if args.json:
            print(cost.as_json(reviews))
            return 0
        lines = [x for rv in reviews for x in cost.render_review(rv)] or [f"no finished item since {since}"]
        if args.record and reviews:
            lines.append(f"{len(reviews)} review(s) recorded (props.cost_review); then brain refresh")
        print("\n".join(lines))
        return 0
    au = cost.audit(led, since, until, args.top)
    name = projs[0].name if len(projs) == 1 else (getattr(args, "scope_node", "") or "all")
    text = cost.render_audit(au, name, usage.now_utc().strftime("%Y-%m-%d %H:%M UTC"))
    out = cost.audit_path(name, since, until)
    snaps = []
    if args.write:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        for p in projs:  # the week's forecast snapshot, what the calibration judges (spec-brain-psychohistory 6)
            try:
                snaps.append(str(forecast.save(forecast.forecast(p, led, usage.now_utc()), snapshot=True)))
            except (forecast.ForecastError, OSError, ValueError) as exc:
                snaps.append(f"{p.name}: no forecast snapshot ({exc})")
    print(cost.as_json(au) if args.json else text + (f"\nwritten to {out}" if args.write else "")
          + "".join(f"\nforecast snapshot: {s}" for s in snaps))
    return 0


def register(sub, ctx) -> None:
    co = sub.add_parser("cost", help="estimate an item from the finished ones, review actual against estimate and "
                                     "budget, audit the estimates (zero token)").add_subparsers(dest="cost_cmd",
                                                                                                required=True)
    ce = co.add_parser("estimate", help="an item (id) or a brief (text, @FILE or -): cost, output, context peak, "
                                        "active time and sessions, median and p25-p75, from the most alike items")
    ce.add_argument("target", help="an item id, or a brief's text (@FILE: the file, -: stdin)")
    ce.add_argument("--class", dest="task_class", choices=cost.CLASSES, help="the task class (default: the item's "
                                                                              "or the brief's, else standard)")
    ce.add_argument("--record", action="store_true", help="write it on the item (props.cost_estimate)")
    ce.add_argument("--json", action="store_true")
    cr = co.add_parser("review", help="finished items' actual against their estimate and brief budget, and why")
    cr.add_argument("item", nargs="?", help="one item (default: the items finished in the window)")
    cr.add_argument("--since", default="last-week", help="the window's start (default last-week)")
    cr.add_argument("--until", help="the window's end, excluded (default: now)")
    cr.add_argument("--record", action="store_true", help="write each review on its item (props.cost_review)")
    cr.add_argument("--json", action="store_true")
    ca = co.add_parser("audit", help="the window's estimates off by more than x1.5 and why, the calibration per "
                                     "class, the costliest sessions, the script candidates")
    ca.add_argument("--since", default="last-week", help="the window's start (default last-week)")
    ca.add_argument("--until", help="the window's end, excluded (default: now)")
    ca.add_argument("--top", type=_whole, default=cost.TOP, help=f"rows per table (default {cost.TOP}; 0: all)")
    ca.add_argument("--write", action="store_true", help="keep it in <BRAIN_HOME>/usage/<project>/audit-*.md, and the "
                                                         "week's forecast snapshot in <BRAIN_HOME>/forecast/<project>")
    ca.add_argument("--json", action="store_true")
    for one in (ce, cr, ca):
        one.add_argument("--scope", help="the items and sessions of the projects of a node's subtree in the scope "
                                         "tree (brain scopes): an id, a path of ids, global, . or ..")


run = cmd_cost
