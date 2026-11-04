"""``brain journal``: the project's journal (notes/journal.md), append-only."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from .. import notes
from ._common import _project, _text

ORDER = 70   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 70   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain journal add [LINE|-|@FILE]... [--title T]   a new dated entry, or lines at the end of today's (append-only)
"""


def cmd_journal(args, root: Path) -> int:
    path = Path(args.file).resolve() if args.file else _project(args, root).journal
    lines = [_text(x) for x in args.lines or []]
    try:
        what = notes.journal_add(path, lines, title=args.title or "", day=args.date)
    except notes.NotesError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    print(f"journal: {'new entry' if what == 'entry' else 'lines added'} in {rel} ({args.date or date.today()})")
    return 0


def register(sub, ctx) -> None:
    jo = sub.add_parser("journal", help="the project's journal (notes/journal.md), append-only").add_subparsers(
        dest="journal_cmd", required=True)
    ja = jo.add_parser("add", help="a new dated entry (--title), or lines at the end of today's entry")
    ja.add_argument("lines", nargs="*", help="one line each (a bullet unless it is one already); '-' reads stdin, "
                                             "@FILE reads FILE")
    ja.add_argument("--title", help="start a new entry: ## <date> — <title>")
    ja.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ja.add_argument("--file", help="the journal (default: the project's, notes/journal.md)")


run = cmd_journal
