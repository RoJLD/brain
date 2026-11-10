"""``brain items``: the backlog filtered, instead of reading the store's YAML or the board by hand (brain.reads)."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import reads
from ._common import _print_json, _read_stores, _whole

ORDER = 21   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 21   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain items [--status S]... [--all] [--priority P]... [--wave X.Y.Z|ID] [--milestone M]... [--prop K[=TEXT]]...
                 [--text WORDS] [--type T]... [--repo R] [--limit N] [--json]   the items matching every filter
                 (default: the open ones), by status, priority and id; --wave: the wave's items now (carried in
                 included) and those whose free-text props.wave names it
"""


def cmd_items(args, root: Path) -> int:
    props = {}
    for p in args.prop or []:
        key, sep, value = p.partition("=")
        props[key] = value if sep else None
    rows: list[dict] = []
    try:
        for store in _read_stores(args, root):
            rows += reads.items(root, store, statuses=args.status, every=args.all, priorities=args.priority,
                                repo=args.repo, props=props, text=args.text, types=args.type, wave=args.wave or "",
                                milestones=args.milestone)
    except reads.ReadError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    shown = rows[:args.limit] if args.limit else rows
    if args.json:
        _print_json(shown)
        return 0
    from research_graph import report
    print("\n".join(report.rows(shown)))
    if len(shown) < len(rows):
        print(f"... {len(rows) - len(shown)} more: --limit 0 lists them all")
    return 0


def register(sub, ctx) -> None:
    it = sub.add_parser("items", help="the backlog filtered (default: the open work items), instead of reading the "
                                      "store's YAML or the board")
    it.add_argument("--status", action="append", help="todo, doing, blocked, done, dropped (repeatable; default: the "
                                                      "open ones)")
    it.add_argument("--all", action="store_true", help="every status")
    it.add_argument("--priority", action="append", help="P0-P3, P1? (a proposal), none (repeatable)")
    it.add_argument("--wave", help="a wave's release (X.Y.Z) or id: its items now, and those whose props.wave names it")
    it.add_argument("--milestone", action="append", help="part_of this milestone (repeatable: any of them)")
    it.add_argument("--prop", action="append", metavar="KEY[=TEXT]", help="items with this prop (whose value contains "
                                                                         "TEXT); repeatable, all must match")
    it.add_argument("--text", help="every word in the id, title, anchor or props")
    it.add_argument("--type", action="append", help="node type (default WorkItem; repeatable)")
    it.add_argument("--repo", help="props.repo / repos, or the repo of props.pr; else the store's own repo")
    it.add_argument("--limit", type=_whole, default=0, help="the first N rows only (0: all)")
    it.add_argument("--json", action="store_true", help="research_graph's item rows")


run = cmd_items
