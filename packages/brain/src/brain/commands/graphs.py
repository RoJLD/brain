"""``brain graphs``: every graph layer and external graph of a project, or of every project, in one list, assembled at
zero token from what the stores, the registry and the code index's records already hold (brain.graphs;
docs/graphs.md)."""

from __future__ import annotations

import json
from pathlib import Path

from .. import graphs
from ._common import _scope

ORDER = 193   # its place in brain --help's list of commands (brain.commands), after brain projects
USAGE_ORDER = 223   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain graphs [--project P | --all] [--json]   every graph of the project (--all: of every project, then those the
                 brain only reads) in one list, at zero token, writing nothing (docs/graphs.md): each store's layers
                 (version, written or generated, node and edge counts, the last commit of their files, query and
                 impact entries, what reads them) and the catalogue's layers it lacks; its overlays; its code index
                 per backend against the branch head (records and git only); its docgraph documents; the source
                 files beside them (decision logs, journals, records, stacks, schedules, memory, rules and
                 procedures, config.json); --json: stable keys, v 1
"""


def cmd_graphs(args, root: Path) -> int:
    reg = graphs.registry(root, _scope(args, root), bool(args.all))
    if args.json:
        print(json.dumps(reg, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    print("\n".join(graphs.lines(reg)))
    return 0


def register(sub, ctx) -> None:
    gr = sub.add_parser("graphs", help="every graph layer and external graph of the project (or --all) in one list, "
                                       "at zero token")
    gr.add_argument("--all", action="store_true", help="every registered project, then the projects the brain only "
                                                       "reads")
    gr.add_argument("--json", action="store_true", help="stable keys (v 1; docs/graphs.md)")


run = cmd_graphs
