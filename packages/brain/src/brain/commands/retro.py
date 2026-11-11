"""``brain retro``: the close-item retro of an item (its friction signals and five questions), or a wave's deep retro
(--wave).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import cost, graph, lessons, usage
from ._common import _scope

ORDER = 420   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 340   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain retro ITEM [--record] [--note LINE]... [--no-scan] [--json] | --wave W
                 the close-item retro: the friction signals of the item's sessions (merges and conflicts, guard
                 refusals, failed tests, waits, tokens against the estimate, the owner's minutes, rework pushes on its
                 PRs), the known lessons of those signals, the five questions; --record writes props.retro (and the
                 --note lines in props.retro_notes); --wave: the deep retro of a wave's items (X.Y.Z or
                 wave-X.Y.Z: the items part_of it or carried to it by props.carried_to; with the items whose
                 props.wave names it, a letter wave such as F or 0.3.2, week of ...), and their retro notes
"""


def cmd_retro(args, root: Path) -> int:
    """brain retro ITEM | --wave W (brain.lessons): the friction signals from brain.cost's ledger, the guards ledger
    and the action records."""
    if bool(args.item) == bool(args.wave):
        raise SystemExit("brain retro: an item id, or --wave W")
    projs = _scope(args, root)
    led = cost.load(projs, root, refresh=not args.no_scan)
    try:
        store = lessons.store_of(projs[0])
    except lessons.LessonError:
        store = None
    if args.wave:
        w = lessons.wave_retro(led, args.wave, store)
        print(cost.as_json(w) if args.json else "\n".join(lessons.render_wave(w)))
        return 0
    if args.item not in led.items:
        raise SystemExit(f"brain retro: {args.item}: no such item in {', '.join(p.name for p in projs)}")
    if not led.items[args.item].sessions:
        print(f"retro {args.item}: no session served it in the ledger yet (brain usage; a session serves the items "
              "it closes, the items naming its PRs, its title's or its brief's)")
    r = lessons.retro(led, args.item, store)
    if args.record:
        today = usage.now_utc().date().isoformat()
        sets = [f"retro={lessons.retro_text(r, today)}"]
        if args.note:
            sets.append("retro_notes=" + " | ".join(" ".join(n.split()) for n in args.note))
        graph.set_item(led.items[args.item].store, args.item, sets)
    if args.json:
        print(cost.as_json(r))
        return 0
    print("\n".join(lessons.render_retro(r)))
    if args.record:
        print(f"recorded on {args.item} (props.retro{', props.retro_notes' if args.note else ''}); then brain refresh")
    return 0


def register(sub, ctx) -> None:
    rt = sub.add_parser("retro", help="the close-item retro of an item (its friction signals and five questions), or "
                                      "a wave's deep retro (--wave)")
    rt.add_argument("item", nargs="?")
    rt.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    rt.add_argument("--wave", help="the wave: X.Y.Z or wave-X.Y.Z (its items part_of it or carried to it), or a "
                                   "wave named by the items' props.wave, e.g. F")
    rt.add_argument("--record", action="store_true", help="write props.retro (and props.retro_notes) on the item")
    rt.add_argument("--note", action="append", help="one of the session's five lines (repeatable)")
    rt.add_argument("--no-scan", action="store_true", help="the token ledger as it is, transcripts not rescanned")
    rt.add_argument("--json", action="store_true")


run = cmd_retro
