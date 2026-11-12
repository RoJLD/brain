"""``brain handover``: the coordinators' hand-over note and the guard's conditions checked before the Remote Control
calls; the chain root, the owner's mark (brain.succession, wi-brain-handover-command). Machine-wide: no root."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import succession

ORDER = 545   # its place in brain --help's list of commands (brain.commands): after sessions
USAGE_ORDER = 545   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain handover write [--from FILE|-] [--successor NAME] [--id ID]   the coordinator's hand-over note in
                 <BRAIN_HOME>/handover/coordinator-<date>-<name>.md, its first line its own app id (From <id> (<name>),
                 <date> UTC), then the successor's name and the body (FILE, - for stdin)
  brain handover check [--id ID] [--successor ID] [--json]   the guard's conditions before Remote Control: a
                 coordinator by name (or a chain root), started by one (or by a root), its note under 6 h old, its
                 successors live and detached; and its predecessor, which the incoming coordinator archives first;
                 exit 1 when the hand-over would be refused, 2 when the app's files cannot be read
  brain handover root [ID] [--reason TEXT] [--clear]   {owner}'s, in their own terminal: mark the session they started
                 as a coordinators' chain root (it hands over without a name; its successor's parent condition holds);
                 no ID: the marked roots
"""


def early(args) -> int:
    try:
        if args.ho_cmd == "write":
            body = ""
            if args.from_ == "-":
                body = sys.stdin.read()
            elif args.from_:
                body = Path(args.from_).read_text(encoding="utf-8")
            f = succession.write_note(body, host=args.id, successor=args.successor or "")
            print(f"hand-over note written: {f}")
            print("next: brain handover check, then the start, Remote Control on for the successor, the children "
                  "told, Remote Control off on yourself (the private brain's coordinator-handover skill)")
            return 0
        if args.ho_cmd == "check":
            r = succession.check(args.id, successor=args.successor or "")
            print(json.dumps(r, indent=1, sort_keys=True) if args.json else "\n".join(succession.lines(r)))
            return 0 if r["ok"] else 1
        if args.ho_cmd == "root":
            if not args.host:
                rows = succession.roots()
                for h, r in sorted(rows.items()):
                    print(f"{h}  {r.get('at', '')}  {r.get('title', '')}  {r.get('reason', '')}".rstrip())
                if not rows:
                    print("no chain root marked")
                return 0
            if args.clear:
                print(f"{args.host}: " + ("mark removed" if succession.clear_root(args.host) else "was not marked"))
                return 0
            succession.mark_root(args.host, args.reason or "")
            print(f"{args.host}: marked a coordinators' chain root (it may hand over; its successor's parent "
                  "condition holds)")
            return 0
    except (succession.SuccessionError, OSError) as exc:
        print(f"brain handover {args.ho_cmd}: {exc}", file=sys.stderr)
        return 2
    return 2


def register(sub, ctx) -> None:
    sp = sub.add_parser("handover", help="the coordinators' hand-over: the note, the guard's conditions, the chain "
                                         "root (brain.succession)").add_subparsers(dest="ho_cmd", required=True)
    w = sp.add_parser("write", help="write this coordinator's hand-over note, its own app id first")
    w.add_argument("--from", dest="from_", metavar="FILE", help="the note's body (- for stdin)")
    w.add_argument("--successor", metavar="NAME", help="the successor's name, e.g. coordinator-034")
    w.add_argument("--id", metavar="ID", help="the session's app id (default CLAUDE_CODE_HOST_SESSION_ID)")
    c = sp.add_parser("check", help="the guard's hand-over conditions for this session, and its predecessor")
    c.add_argument("--id", metavar="ID", help="the session's app id (default CLAUDE_CODE_HOST_SESSION_ID)")
    c.add_argument("--successor", metavar="ID", help="the successor to check (default the first one found)")
    c.add_argument("--json", action="store_true", help="stable keys")
    r = sp.add_parser("root", help=f"{ctx.who}'s, in their own terminal: mark a coordinators' chain root")
    r.add_argument("host", nargs="?", metavar="ID", help="the root session's app id (local_<uuid>)")
    r.add_argument("--reason", metavar="TEXT", help="why, kept with the mark")
    r.add_argument("--clear", action="store_true", help="remove the mark")
