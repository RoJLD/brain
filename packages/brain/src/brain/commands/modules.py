"""``brain modules``: the module map: each open item's module against the store's modules.yaml, the generated view
notes/modules_graph.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import modules, skew
from ._common import _project, _store, _store_label
from ._stores import _module_view

ORDER = 30   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 40   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain modules [--write] [--force] [--check] [--json]   the module map: each open item's props.module (and
                 props.modules_secondary) against the store's modules.yaml; the view notes/modules_graph.md (beside
                 the store's board when it is not in notes/; per module its phase, status, items done and open, and
                 the gaps), written by brain sync; --check: the
                 open items with no module, or a module the registry does not know (brain check warns of them);
                 under config.json views.strict, another engine than engine.pin writes nothing (--force)
"""


def cmd_modules(args, root: Path) -> int:
    """brain modules (brain.modules): the view printed, written with --write; --check: the module map's problems."""
    store = _store(args, root)
    if not modules.applies(store):
        raise SystemExit(f"brain modules: no {modules.REGISTRY} in {store} (the registry of modules)")
    if args.write and skew.refuse_view(root, "modules --write", args.force, f"the committed {modules.FILE}"):
        return 1
    if args.write:   # first, so --write --check writes the view and then checks the map
        view = _module_view(_project(args, root), root, store)
        print(f"view: {view} " + ("written" if modules.write(root, store, _store_label(root, store), view)
                                  else "unchanged"))
    if args.check:
        found = modules.problems(store)
        print(json.dumps(found, indent=1) if args.json else "\n".join(found) or "module map: every open item placed")
        return 1 if found else 0
    if args.json:
        print(json.dumps(modules.data(store), indent=1, ensure_ascii=False, default=str))   # a YAML date
    elif not args.write:
        print(modules.render(store, _store_label(root, store)), end="")
    return 0


def register(sub, ctx) -> None:
    mo = sub.add_parser("modules", help="the module map: each open item's module against the store's modules.yaml, "
                                        "the generated view notes/modules_graph.md")
    mo.add_argument("--write", action="store_true", help="write notes/modules_graph.md (brain sync does)")
    mo.add_argument("--force", action="store_true", help="--write even when the running engine is not config.json "
                                                         "engine.pin (refused under views.strict)")
    mo.add_argument("--check", action="store_true", help="the open items with no module or an unknown one (exit 1)")
    mo.add_argument("--json", action="store_true", help="the map as JSON (each module's counts, the problems); with "
                                                        "--check, the problems")


run = cmd_modules
