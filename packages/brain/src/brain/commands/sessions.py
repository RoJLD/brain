"""``brain sessions``: the session tree: both ids, role, parent, children, state, context and each child's report (zero
token).
"""

from __future__ import annotations

import argparse

ORDER = 540   # its place in brain --help's list of commands (brain.commands)
PHASE = "early"   # its handlers: early only, before any root is resolved (brain.commands)
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
                        go before or after tree/show (only --json applies to self, before or after it)
  brain sessions self [--json]   this session's own app id (local_..., from $CLAUDE_CODE_HOST_SESSION_ID when the app's
                        file of that id names this transcript), the one a report to a coordinator is signed with;
                        exit 1 outside an app session, on a malformed id, or on an id inherited from another
                        session's shell (a claude started there): the app's get_session self tells it then
"""
NO_PROJECT = {"sessions"}   # its parsers that take no --project after them


def cmd_self(as_json: bool) -> int:
    """brain sessions self: this session's app id, the one its reports are signed with (wi-brain-brief-own-id): never
    the coordinator's, nor the shared notes folder's, which names the first coordinator."""
    import json
    import os
    import sys

    from .. import sessions
    raw = os.environ.get(sessions.HOST_ENV, "").strip()
    why, inherited = "", False
    if not raw:
        why = "no app session id here ($CLAUDE_CODE_HOST_SESSION_ID is not set)"
    elif not sessions.HOST_RE.match(raw):
        why = "$CLAUDE_CODE_HOST_SESSION_ID is not an app session id (local_ and a uuid)"
    elif not sessions.host_for(env={**os.environ, sessions.HOST_ENV: raw}):
        # a claude started from another session's shell inherits that session's id (review of #34, finding 50)
        why, inherited = ("$CLAUDE_CODE_HOST_SESSION_ID is inherited from another session's shell (its app file "
                          "names another transcript)"), True
    sid = "" if why else raw
    if as_json:
        print(json.dumps({"id": sid, "source": sessions.HOST_ENV if raw else "", "inherited": inherited}))
    elif sid:
        print(sid)
    if why:
        print(f"brain sessions self: {why}: in the desktop app, its get_session tool with the id self tells it",
              file=sys.stderr)
        return 1
    return 0


def cmd_sessions(args) -> int:
    """brain sessions [tree [ID] | show ID | self] (brain.sessions): machine-wide, no graph store."""
    from .. import sessions
    if args.sessions_cmd == "self":
        return cmd_self(args.json)
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
    me = ses_sub.add_parser("self", help="this session's own app id (local_...), the one its reports are signed with")
    me.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    for sp_ in (ses, *(p for n, p in ses_sub.choices.items() if n != "self")):
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
