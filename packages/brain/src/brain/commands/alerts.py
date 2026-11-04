"""``brain alerts``: each project's open alerts (scheduler, ledger, stacks, code index, audit, its events and files);
--notify sends the changes through brain notify.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import alerts, resume
from ._common import _scope, _text

ORDER = 460   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 370   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain alerts [--project P | --all] [--quick] [--json] [--fail-on LEVEL] [--notify [--dry-run]]
                 the open alerts of each project, at zero token: the scheduler's tasks (missed passes against their
                 cadence, 2 before an alert; killed, failed, disabled, silent), the exec ledger, watched stacks, the
                 code index, the audit debt above the written view, the project's alert events and files (brain
                 status shows them in the project's section); --quick: the files and events only; --fail-on: exit 1
                 when one is open at that level or above; --notify: the pass a scheduled task runs, which sends each
                 new, risen or failed alert through brain notify at its level (resolved ones at info) and records
                 the changes in $BRAIN_HOME/alerts (--dry-run: what it would send, nothing recorded); without its
                 channel's variable ($BRAIN_NTFY_TOPIC) it sends nothing and says so in one line
  brain alerts raise KEY [MESSAGE|-|@FILE] --level L [--task T] [--source S] [--code C] [--link URL]
  brain alerts resolve KEY [MESSAGE] [--level L]   a project's alert event (kind alert of the event schema) in
                 $BRAIN_HOME/ledger/alert-<yyyy-mm>.jsonl, what its writers call instead of a tracked alerts file
"""


def cmd_alerts(args, root: Path) -> int:
    """``brain alerts``: the open alerts of the project here or --project's, or every one with --all; --notify: the
    pass that sends the changes since the last one through brain notify. raise | resolve: an alert event."""
    if args.alerts_cmd:
        p = getattr(args, "project_obj", None) or resume.project_for(root)
        code = args.code
        if code is not None and code.lstrip("-").isdigit():
            code = int(code)
        try:
            ev = alerts.emit(p.name, args.key, args.level or ("info" if args.alerts_cmd == "resolve" else "warn"),
                             _text(args.message).strip(), state="open" if args.alerts_cmd == "raise" else "resolved",
                             task=args.task or "", source=args.source or "", code=code, link=args.link or "")
        except ValueError as exc:
            print(f"brain: {exc}", file=sys.stderr)
            return 2
        print(f"alert {ev['state']}: {p.name} {ev['key']} ({ev['severity']})")
        return 0
    if args.dry_run and not args.notify:
        raise SystemExit("brain: --dry-run goes with --notify")
    scope = _scope(args, root)
    data = alerts.run(scope, quick=args.quick, root=root)
    sent = alerts.notify_pass(data, {p.name: p for p in scope}, dry_run=args.dry_run) if args.notify else None
    if args.json:
        print(json.dumps({**data, **({"notify": sent} if sent is not None else {})}, ensure_ascii=False, indent=1,
                         sort_keys=True))
    else:
        print("\n".join(alerts.render(data) + (["notify:"] + ["  " + x for x in sent] if sent is not None else [])))
    if args.fail_on:
        worst = max((alerts.RANK[a["level"]] for d in data["projects"] for a in d.get("alerts", [])), default=-1)
        return 1 if worst >= alerts.RANK[args.fail_on] else 0
    return 0


def register(sub, ctx) -> None:
    al = sub.add_parser("alerts", help="each project's open alerts (scheduler, ledger, stacks, code index, audit, its "
                                       "events and files); --notify sends the changes through brain notify")
    al.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    al.add_argument("--all", action="store_true", help="every project of the registry")
    al.add_argument("--quick", action="store_true", help="the files and events only: no scheduler, stack, code index "
                                                         "or audit probe")
    al.add_argument("--json", action="store_true", help="stable keys, no timestamp of its own")
    al.add_argument("--fail-on", choices=list(alerts.LEVELS), help="exit 1 when an alert at this level or above is "
                                                                    "open")
    al.add_argument("--notify", action="store_true", help="send the new, risen and failed alerts through brain notify "
                                                          "(resolved ones at info) and record the pass")
    al.add_argument("--dry-run", action="store_true", help="with --notify: what would be sent; nothing sent or recorded")
    als = al.add_subparsers(dest="alerts_cmd")
    for name, text in (("raise", "open an alert (or update it: a new level or message)"),
                       ("resolve", "resolve an alert")):
        a = als.add_parser(name, help=f"{text}: an alert event in $BRAIN_HOME/ledger/alert-<yyyy-mm>.jsonl")
        a.add_argument("key", help="the alert's stable id within the project (freshness:returns_matic)")
        a.add_argument("message", nargs="?", default="", help="one line ('-': stdin, @FILE: the file)")
        a.add_argument("--level", choices=list(alerts.LEVELS),
                       help="its level, the notify level it is sent at (default: warn; resolve: info)")
        a.add_argument("--task", help="what it is about (default: the key)")
        a.add_argument("--source", help="who raises it: a monitor, a CLI, a watchdog")
        a.add_argument("--code", help="a catalogued code (an exit code, a scheduler result, a name)")
        a.add_argument("--link", help="a URL or a path to look at")


run = cmd_alerts
