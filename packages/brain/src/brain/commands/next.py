"""``brain next``: what comes next, from the graph's waves at zero token (brain.waves): the current wave, its
carried items first, then its startable items, what waits on the owner, the first round of its lots (brain.lots,
brain wave plan), then the next wave.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import lots, waves
from ._common import _project, _store

ORDER = 56   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 56   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain next [--json]   the current wave (the lowest release not closed): its items carried from an earlier wave
                 first, then those that can start, what waits on {owner} (props.open, external_blocker, pending DDRs),
                 the other open ones, the first round of its lots (brain wave plan), then the next wave; zero token,
                 from the graph (its view: plan_graph.md)
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
        except ValueError:
            wp = None
    if args.json:
        print(json.dumps(rep | {"lots": wp.as_dict() if wp else None}, indent=2, ensure_ascii=False))
    else:
        out = waves.render_next(rep)
        at = next((k for k, line in enumerate(out) if line.startswith("Next:")), len(out))
        print("\n".join(out[:at] + (lots.summary(wp) if wp else []) + out[at:]))   # the current wave's, before the next
    return 0


def register(sub, ctx) -> None:
    nx = sub.add_parser("next", help=f"the current wave: carried items first, then startable ones, what waits on "
                                     f"{ctx.who}, then the next wave (zero token)")
    nx.add_argument("--json", action="store_true", help="the data, as JSON")


run = cmd_next
