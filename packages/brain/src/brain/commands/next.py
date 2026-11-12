"""``brain next``: what comes next, from the graph's waves at zero token (brain.waves): the current wave, its
quick wins, its carried items first, then its startable items, each group ranked (brain.ranking), what waits on the
owner, the first round of its lots (brain.lots, brain wave plan), then the next wave.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import lots, waves
from ._common import _project, _store

ORDER = 56   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 56   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain next [--explain] [--json]   the current wave (the lowest release not closed): its quick wins (size S, high
                 value) first, its quick-win slot (a fifth of its places: what fills it, the candidates outside the
                 wave while a place is free), its items carried from an earlier wave, then those that can start, what waits on {owner}
                 (props.open, external_blocker, pending DDRs), the other open ones, the first round of its lots (brain
                 wave plan), then the next wave; zero token, from the graph (its view: plan_graph.md). Each group is
                 ranked by {owner}'s priority (confirmed before proposed), then {owner}'s order (props.order), then
                 value over effort (WSJF: the value derived from the features delivered, a milestone moved and the
                 items unblocked, or props.value high|medium|low with props.value_reason; the effort from
                 props.size); --explain: each score's parts and the values {owner} set (brain.ranking)
"""


def cmd_next(args, root: Path) -> int:
    store = _store(args, root)
    rep = waves.next_report(waves.load(store, root))
    wp = None
    if rep["current"] is not None:
        try:
            name = _project(args, root).name
        except SystemExit:
            name = ""
        try:
            wp = lots.plan(store, root, rep["current"]["id"], name)
        except Exception:   # noqa: BLE001 - the lots are a summary: brain next prints the waves whatever they say
            wp = None
    if args.json:
        print(json.dumps(rep | {"lots": wp.as_dict() if wp else None}, indent=2, ensure_ascii=False))
    else:
        out = waves.render_next(rep, explain=args.explain)
        at = next((k for k, line in enumerate(out) if line.startswith("Next:")), len(out))
        print("\n".join(out[:at] + (lots.summary(wp) if wp else []) + out[at:]))   # the current wave's, before the next
    return 0


def register(sub, ctx) -> None:
    nx = sub.add_parser("next", help=f"the current wave: carried items first, then startable ones, what waits on "
                                     f"{ctx.who}, then the next wave (zero token)")
    nx.add_argument("--json", action="store_true", help="the data, as JSON")
    nx.add_argument("--explain", action="store_true", help="each carried and startable item's score: value (its "
                                                           "parts, or the owner's props.value) over effort (its size)")


run = cmd_next
