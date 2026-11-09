"""``brain sessions``: the session tree: both ids, role, parent, children, state, context and each child's report (zero
token).
"""

from __future__ import annotations

import argparse

ORDER = 540   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 200   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain sessions [tree [ID] | show ID [--report]] [--hours H] [--all] [--json]   the session tree at zero token, from
                        the desktop app's session files (a closed list of keys, read only), the SessionStart events
                        and the briefs' hash: both ids of each session (the app's local_ id, the transcript's), its
                        short name, role (master, sub, relay, solo), parent, children live/started, state and context
                        against its budget (the brief's; a master's: usage.master_budget, else the model's window);
                        tree: the families with a member active in the last H hours, each child's end-of-turn report
                        (its PRs, head, items, DDRs, what it waits on, what comes next); show: one session, by either
                        id (a prefix of 8 or more) or its short name, and what a message would meet (live, idle,
                        archived); --report: its last final message in full, read from its transcript; the options
                        go before or after tree/show
"""
NO_PROJECT = {"sessions"}   # its parsers that take no --project after them


def cmd_sessions(args) -> int:
    """brain sessions [tree [ID] | show ID] (brain.sessions): machine-wide, no graph store."""
    from .. import sessions
    try:
        print(sessions.main(args.sessions_cmd or "list", getattr(args, "ref", "") or "", hours=args.hours,
                            every=args.all, briefs=not args.no_briefs, as_json=args.json,
                            report=getattr(args, "report", False)))
    except sessions.SessionsError as exc:
        raise SystemExit(f"brain sessions: {exc}") from None
    return 0


def register(sub, ctx) -> None:
    ses = sub.add_parser("sessions", help="the session tree: both ids, role, parent, children, state, context and "
                                          "each child's report (zero token)")
    ses_sub = ses.add_subparsers(dest="sessions_cmd")
    for name, help_ in (("tree", "the families with a live member, or ID's family, with the children's reports"),
                        ("show", "one session by either id or its short name: what a message would meet")):
        sp_ = ses_sub.add_parser(name, help=help_)
        sp_.add_argument("ref", nargs="?" if name == "tree" else None, default="",
                         help="an app id (local_..., a prefix of 8 or more), a transcript id or a short name")
        if name == "show":
            sp_.add_argument("--report", action="store_true", help="its last final message in full, from its "
                                                                   "transcript (never stored)")
    for sp_ in (ses, *ses_sub.choices.values()):
        # the subcommands' own copies default to SUPPRESS: given before tree/show, an option is not reset by the
        # subparser's default (review of #34, finding 56)
        keep = {} if sp_ is ses else {"default": argparse.SUPPRESS}
        sp_.add_argument("--hours", type=float, default=24.0 if sp_ is ses else argparse.SUPPRESS,
                         help="active in the last H hours (default 24)")
        sp_.add_argument("--all", action="store_true", help="every session, archived ones included", **keep)
        sp_.add_argument("--no-briefs", action="store_true", help="skip the token ledger's brief hash", **keep)
        sp_.add_argument("--json", action="store_true", **keep)


def early(args) -> int:
    """The machine's sessions: no graph store."""
    return cmd_sessions(args)
