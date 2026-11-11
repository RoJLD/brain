"""``brain notify``: the notification channels: ntfy, Telegram, e-mail, per project and level (projects.yaml notify:).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import notify
from ._common import _notify_project, _scope, _text

ORDER = 480   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 360   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain notify send [MESSAGE|-|@FILE] --level info|warn|error|critical [--title T] [--source S] [--key K]
                 [--link URL] [--channel C]... [--force] [--dry-run] [--json]
                 through the project's route for that level (projects.yaml notify:): ntfy, Telegram, e-mail, the
                 first that delivers or every one; --channel: these channels only; --key: not again within the
                 throttle (--force: anyway); --dry-run: print what would be sent; exit 1 when nothing delivered
  brain notify status [--all]     channels (their environment variables set or missing, never their values), routes,
                 the notifications waiting in the outbox (sent again by the alerts pass)
  brain notify setup ntfy|telegram|email|CHANNEL [--find-chat]   a channel's setup steps; --find-chat lists the
                 chats that wrote to the Telegram bot (it sends nothing)
"""


def cmd_notify(args, root: Path) -> int:
    try:
        if args.notify_cmd == "status":
            for i, p in enumerate(_scope(args, root) if args.all else [_notify_project(args, root)]):
                print(("\n" if i else "") + "\n".join(notify.status(notify.config(p))))
            return 0
        cfg = notify.config(_notify_project(args, root))
        if args.notify_cmd == "setup":
            print("\n".join(notify.setup(cfg, args.target, find_chat=args.find_chat)))
            return 0
        body = _text(args.message)
        if not body.strip():
            raise notify.NotifyError("give the message (MESSAGE, - for stdin or @FILE)")
        msg = notify.Message(cfg.project, args.level, body, args.title or "", args.source or "", args.key or "",
                             args.link or "")
        res = notify.send(cfg, msg, only=args.channel, dry_run=args.dry_run, force=args.force)
    except notify.NotifyError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res.to_json(), ensure_ascii=False, indent=1))
    else:
        print("\n".join(res.lines()))
        if res.status == "dry-run":
            print(f"title: {msg.heading()}\n" + "\n".join("  " + x for x in msg.text().splitlines()))
    return res.code


def register(sub, ctx) -> None:
    no = sub.add_parser("notify", help="the notification channels: ntfy, Telegram, e-mail, per project and level "
                                       "(projects.yaml notify:)").add_subparsers(dest="notify_cmd", required=True)
    ns = no.add_parser("send", help="send through the project's route for the level; exit 1 when nothing delivered")
    ns.add_argument("message", nargs="?", default="", help="the text ('-': stdin, @FILE: the file)")
    ns.add_argument("--level", required=True, choices=list(notify.LEVELS))
    ns.add_argument("--title", help="a short title (default: the message's first line)")
    ns.add_argument("--source", help="who sends: watchdog, decision, a task's name...")
    ns.add_argument("--key", help="an alert's stable id: not sent again at this level within the throttle")
    ns.add_argument("--link", help="a URL the notification opens")
    ns.add_argument("--channel", action="append", help="these declared channels only, every one of them (a test)")
    ns.add_argument("--force", action="store_true", help="send even within the throttle")
    ns.add_argument("--dry-run", action="store_true", help="print what would be sent, send nothing")
    ns.add_argument("--json", action="store_true")
    nt = no.add_parser("status", help="channels, their environment variables (set or missing, never their values), "
                                      "the project's routes, the outbox's waiting count, the last sends")
    nu = no.add_parser("setup", help="a channel's setup steps (the TUI wizard's): ntfy, telegram, email or a name")
    nu.add_argument("target", metavar="CHANNEL")
    nu.add_argument("--find-chat", action="store_true", help="telegram: the chats that wrote to the bot (getUpdates; "
                                                             "sends nothing)")
    for sp in (ns, nt, nu):
        sp.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    nt.add_argument("--all", action="store_true", help="every project of the registry")


run = cmd_notify
