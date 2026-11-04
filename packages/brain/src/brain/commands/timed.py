"""``brain timed``: run a command and append its execution-time event to the ledger."""

from __future__ import annotations

import argparse

from .. import timing

ORDER = 440   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 490   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain timed [--task T] [--project P] [--version V] [--shell] [--quiet] -- COMMAND...
                 run COMMAND (input and output untouched, exit code passed through) and append its event (start, end,
                 duration, exit, host, project, task, version) to $BRAIN_HOME/ledger/exec-<yyyy-mm>.jsonl, one line
                 under a lock (brain.timing; projects import brain.timing.timed, a decorator and context manager)
"""


def register(sub, ctx) -> None:
    tm = sub.add_parser("timed", help="run a command and append its execution-time event to the ledger")
    tm.add_argument("--task", help="the step's name (default: the command line)")
    tm.add_argument("--project", default=argparse.SUPPRESS, help="default: $BRAIN_PROJECT, else the registered project "
                                                                 "of the current folder, else the repo's name")
    tm.add_argument("--version", dest="code_version", help="what runs (default: $BRAIN_VERSION, else the short SHA of "
                                                           "HEAD of the current folder's repo)")
    tm.add_argument("--shell", action="store_true", help="run the command line through the system shell")
    tm.add_argument("--quiet", action="store_true", help="no line on stderr")
    tm.add_argument("command", nargs=argparse.REMAINDER, help="-- then the command and its arguments")


def early(args) -> int:
    """Machine-wide ledger: a project name is a label, the registry is not needed."""
    return timing.run(args.command, task=args.task, project=args.project, version=args.code_version,
                      shell=args.shell, quiet=args.quiet)
