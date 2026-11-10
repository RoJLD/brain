"""``brain next``: what comes next, from the graph's waves at zero token (brain.waves): the current wave, its
carried items first, then its startable items, what waits on the owner, then the next wave.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import waves
from ._common import _store

ORDER = 56   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 56   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain next [--json]   the current wave (the lowest release not closed): its items carried from an earlier wave
                 first, then those that can start, what waits on {owner} (props.open, external_blocker, pending DDRs),
                 the other open ones, then the next wave; zero token, from the graph (its view: plan_graph.md)
"""


def cmd_next(args, root: Path) -> int:
    rep = waves.next_report(waves.load(_store(args, root), root))
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print("\n".join(waves.render_next(rep)))
    return 0


def register(sub, ctx) -> None:
    nx = sub.add_parser("next", help=f"the current wave: carried items first, then startable ones, what waits on "
                                     f"{ctx.who}, then the next wave (zero token)")
    nx.add_argument("--json", action="store_true", help="the data, as JSON")


run = cmd_next
