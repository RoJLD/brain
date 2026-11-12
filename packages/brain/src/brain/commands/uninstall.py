"""``brain uninstall``: every trace of the brain on this machine its store registry knows (brain.uninstall), as a plan,
removed with --apply; --purge adds the data stores, the stores nothing else keeps only once their recovery copy is
confirmed.
"""

from __future__ import annotations

import json
import sys

from ._common import root_of

ORDER = 472   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 382   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain uninstall [--purge] [--confirm-recovery STORE...] [--apply] [--json]   every trace of the brain on this
                 machine its store registry knows, as a plan (brain.uninstall): the scheduled tasks it installed, the
                 Claude Code plugin and marketplace (claude CLI), the launcher on the PATH, the engine's install stores
                 in BRAIN_HOME; --purge adds every data store, this machine's device key and BRAIN_HOME itself: a
                 derived store goes, one nothing else keeps (the ledger, the vault, the sessions...) is held until
                 --confirm-recovery names it (or all) once its recovery copy is confirmed; --apply removes, {owner}'s
                 own (refused in a Claude Code session's shell); Claude Code's transcripts and the brain's repo stay
"""


def register(sub, ctx) -> None:
    un = sub.add_parser("uninstall", help="every trace of the brain on this machine, as a plan; --apply removes it, "
                                          "--purge adds the data")
    un.add_argument("--purge", action="store_true", help="the data stores too, this machine's device key and "
                                                         "BRAIN_HOME itself")
    un.add_argument("--confirm-recovery", nargs="+", default=[], metavar="STORE",
                    help="the stores nothing else keeps whose recovery copy is confirmed (their names in the plan, "
                         "keystore for the device key, or all)")
    un.add_argument("--apply", action="store_true", help="remove what the plan says (the owner's own terminal)")
    un.add_argument("--json", action="store_true")


def early(args) -> int:
    from .. import config, uninstall
    from ..detail import refused
    confirmed = set(args.confirm_recovery)
    bad = uninstall.unknown_names(confirmed)
    if bad:
        print(f"brain uninstall: --confirm-recovery names no store here: {', '.join(bad)}", file=sys.stderr)
        return 2
    steps = uninstall.plan(config.load(root_of(args)), args.purge, confirmed)
    why = refused() if args.apply else ""
    done = uninstall.apply(steps) if args.apply and not why else [(s, "") for s in steps]
    if args.json:
        print(json.dumps({"purge": args.purge, "applied": bool(args.apply and not why),
                          "steps": [{"kind": s.kind, "name": s.name, "action": s.action, "line": s.line,
                                     "outcome": o} for s, o in done]}, indent=2))
    else:
        for s, outcome in done:
            print(s.line + (f"  [{outcome}]" if outcome else ""))
        if not args.apply:
            print("(plan only: --apply removes it, in your own terminal)")
    if why:
        print(f"brain uninstall: --apply refused: {why}", file=sys.stderr)
        return 2
    return 1 if any(o.startswith("failed") for _, o in done) else 0
