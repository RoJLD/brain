"""``brain capture``: hook entry: the hook JSON on stdin (prints nothing)."""

from __future__ import annotations

from .. import capture

ORDER = 550   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 390   # its usage lines' place in brain --help's epilog
RUNS_VIA = {   # brain perf --usage: how a subcommand that may never run from the CLI is reached (brain.adoption)
    "capture": "wired: the capture hook (capture.sh) runs hooks/capture.py on each event, not the CLI",
}
USAGE = """\
  brain capture EVENT [git|gh]   the hooks' entry (hook JSON on stdin; prints nothing)
"""
NO_PROJECT = {"capture"}   # its parsers that take no --project after them


def register(sub, ctx) -> None:
    cap = sub.add_parser("capture", help="hook entry: the hook JSON on stdin (prints nothing)")
    cap.add_argument("event", choices=["session-start", "post-tool-use", "stop", "session-end"])
    cap.add_argument("family", nargs="?", default="", choices=["", "git", "gh"])


def early(args) -> int:
    """The hooks' entry: no root."""
    return capture.main([args.event] + ([args.family] if args.family else []))
