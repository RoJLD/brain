"""``brain usage``: the token ledger: what the sessions cost, by project, item, class, phase, tool, command, day...;
distributions and script candidates; quota: the plan's quota readings and forecast (zero token).
"""

from __future__ import annotations

from pathlib import Path

from .. import config, cost, governor, projects, quota, usage
from ._common import _scope, _when, _whole

ORDER = 160   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 510   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain usage [--project P | --all] [--since WHEN] [--until WHEN] [--by DIM | --report daily|weekly] [--top N]
                 [--no-scan | --rescan] [--json]   the token ledger at zero token ($BRAIN_HOME/usage/sessions.json,
                 scanned from the transcripts that changed): the sessions' tokens and cost at API prices by project,
                 item, pr, class, kind, theme, milestone, model, phase, tool, command, skill, session, family (a
                 session and its sub-sessions), day or week, with the distribution per unit (median, p25-p75, p90),
                 and the script candidates (3-step sequences repeated across sessions); WHEN: Nd, Nw, today,
                 yesterday, last-week, last-month or YYYY-MM-DD (default 7d)
  brain usage quota [--observe PCT [--resets TIME] [--at TIME]] [--window week|5h] [--no-scan] [--json]
                 the plan's quota (brain.quota): --observe notes a get_usage reading (percent used, read at --at,
                 default now; the window resets at --resets, get_usage's resetsAt, default the last reading's moved
                 by whole weeks) in $BRAIN_HOME/usage/quota.jsonl; then the conversion of the ledger's API-price cost
                 into a share of the window, the percent now, at the reset at the last 24 h's pace, what the live
                 sessions have left, how many startable P0/P1 items fit, and the advice (open waves, only P0/P1,
                 none); written to $BRAIN_HOME/usage/quota.json for the cockpit
  brain usage guard [--json]   the usage governor (brain.governor, the PreToolUse hook on start_session, Agent and
                 Workflow): the quota windows it reads, the sessions running and the brainstorms open on this
                 machine, the committed memory, the caps (config.json usage.guard, lowered by the project's usage:)
                 and what a new session, a brainstorm, a subagent and a workflow would get now (ask at WARN, refuse at
                 CRITICAL, past a cap or while the newest reading is stale)
  brain usage allow [--hours H] [--reason TEXT]   {owner}'s override of the usage governor for H hours (default 2;
                 0 ends it), run in their own terminal: the guards refuse it to a session
"""


def cmd_usage(args, root: Path) -> int:
    """The token ledger read back (brain.usage, brain.cost): the project here or --project's sessions, or every one."""
    projs = _scope(args, root)
    if args.rescan:
        usage.update(rescan=True)
    if args.what == "quota":
        return _quota(args, root, projs)
    if args.what in ("guard", "allow"):
        return _governor(args, root)
    led = cost.scoped(cost.load(projs, root, refresh=not (args.no_scan or args.rescan)), projs, args.all)
    by = {"daily": "day", "weekly": "week"}.get(args.report or "", args.by)
    rep = cost.report(led, _when(args.since, "7d"), _when(args.until), by,
                      usage.plans_from(config.load(root).get("usage")))
    print(cost.as_json(rep) if args.json else "\n".join(cost.render_report(rep, args.top)))
    return 0


def _quota(args, root: Path, projs: list[projects.Project]) -> int:
    """brain usage quota (brain.quota): note a reading, then the forecast of the window."""
    now = usage.now_utc()
    try:
        if args.observe is not None:
            rec = quota.observe(args.observe, args.window, quota.parse_time(args.at, now) if args.at else None,
                                quota.parse_time(args.resets, now) if args.resets else None,
                                usage.plans_from(config.load(root).get("usage")))
            if not args.json:
                print(f"noted: {rec['window']} {rec['pct']:g} % at {rec['at']}, resets {rec['resets']} "
                      f"({quota.readings_file()})")
        elif args.at or args.resets:
            raise quota.QuotaError("--at and --resets go with --observe")
        fc = quota.run(cost.load(projs, root, refresh=not (args.no_scan or args.rescan)), projs, now, args.window)
    except quota.QuotaError as exc:
        raise SystemExit(f"brain: {exc}") from None
    print(cost.as_json(fc) if args.json else "\n".join(quota.render(fc)))
    return 0


def _governor(args, root: Path) -> int:
    """brain usage guard | allow (brain.governor): what the usage hook would decide now; the owner's override."""
    if args.what == "allow":
        if args.hours is not None and args.hours < 0:
            raise SystemExit("brain: --hours is 0 or more")
        rec = governor.allow(args.hours if args.hours is not None else governor.ALLOW_HOURS, args.reason or "")
        print(cost.as_json(rec) if args.json else f"usage guard lifted until {rec['until']} ({governor.allow_file()})"
              if rec else "usage guard override ended")
        return 0
    rep = governor.report(str(Path.cwd()))
    print(cost.as_json(rep) if args.json else "\n".join(governor.render(rep)))
    return 0


def register(sub, ctx) -> None:
    us = sub.add_parser("usage", help="the token ledger: what the sessions cost, by project, item, class, phase, "
                                      "tool, command, day...; distributions and script candidates; quota: the plan's "
                                      "quota readings and forecast (zero token)")
    us.add_argument("what", nargs="?", choices=("quota", "guard", "allow"),
                    help="quota: note a get_usage reading (--observe) and forecast the plan's quota window; guard: what "
                         "the usage governor would decide now; allow: the owner's override of it (their own terminal)")
    us.add_argument("--observe", type=float, metavar="PCT",
                    help="quota: the percent used get_usage reads for --window, noted with its time")
    us.add_argument("--window", choices=tuple(quota.WINDOWS), default="week", help="quota: the window (default week)")
    us.add_argument("--resets", metavar="TIME", help="quota: when the window resets (get_usage's resetsAt, ISO; "
                                                     "default the last reading's, moved by whole weeks)")
    us.add_argument("--at", metavar="TIME", help="quota: when the reading was taken (ISO; default now)")
    us.add_argument("--hours", type=float, help="allow: how long the override holds (default 2; 0 ends it)")
    us.add_argument("--reason", help="allow: why, kept with the override")
    us.add_argument("--all", action="store_true", help="every session on this machine, whatever its project")
    us.add_argument("--since", help="Nd, Nw, today, yesterday, last-week, last-month or YYYY-MM-DD (default 7d)")
    us.add_argument("--until", help="the same, excluded (default: now)")
    us.add_argument("--by", choices=cost.DIMS, default="summary",
                    help="one breakdown (default: a summary of project, item, class, phase, tool, command and the "
                         "script candidates)")
    us.add_argument("--report", choices=("daily", "weekly"), help="the same as --by day or --by week")
    us.add_argument("--top", type=_whole, default=cost.TOP, help=f"rows per table (default {cost.TOP}; 0: all)")
    us.add_argument("--no-scan", action="store_true", help="read the ledger as it is, without scanning the "
                                                          "transcripts that changed")
    us.add_argument("--rescan", action="store_true", help="scan every transcript again (after a scanner change)")
    us.add_argument("--json", action="store_true")


run = cmd_usage
