"""``brain journal``: the project's journal (notes/journal.md), append-only, and its last entries read back."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from .. import notes, reads
from ._common import _print_json, _project, _text, _whole

ORDER = 70   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 70   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain journal add [LINE|-|@FILE]... [--title T]   a new dated entry, or lines at the end of today's (append-only)
  brain journal last [N] [--titles] [--json]   the last N dated entries (default 1; 0: all), instead of reading the
                 journal by hand; --titles: their headings only
"""


def cmd_last(args, root: Path) -> int:
    """``brain journal last``: the journal's last entries (brain.reads)."""
    path = Path(args.file).resolve() if args.file else _project(args, root).journal
    try:
        entries = reads.journal_last(path, args.n)
    except reads.ReadError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print_json(entries)
    elif args.titles:
        print("\n".join(f"{e['day']}  {e['title']}" for e in entries))
    else:
        print("\n\n".join(e["text"] for e in entries))
    return 0


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
    jo = sub.add_parser("journal", help="the project's journal (notes/journal.md), append-only: add, "
                                        "last").add_subparsers(
        dest="journal_cmd", required=True)
    ja = jo.add_parser("add", help="a new dated entry (--title), or lines at the end of today's entry")
    ja.add_argument("lines", nargs="*", help="one line each (a bullet unless it is one already); '-' reads stdin, "
                                             "@FILE reads FILE")
    ja.add_argument("--title", help="start a new entry: ## <date> — <title>")
    ja.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ja.add_argument("--file", help="the journal (default: the project's, notes/journal.md)")
    jl = jo.add_parser("last", help="the last N dated entries (default 1; 0: all), instead of reading the journal")
    jl.add_argument("n", nargs="?", type=_whole, default=1, metavar="N")
    jl.add_argument("--titles", action="store_true", help="their headings only")
    jl.add_argument("--json", action="store_true", help="[{day, title, line, text}], oldest first")
    jl.add_argument("--file", help="the journal (default: the project's, notes/journal.md)")


def run(args, root: Path) -> int:
    return (cmd_last if args.journal_cmd == "last" else cmd_journal)(args, root)
