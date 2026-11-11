"""``brain modules``: the module map: each open item's module against the store's modules.yaml (or the registry
config.json modules.store names), the generated view notes/modules_graph.md, the import's checks and report.
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
  brain modules [--write] [--force] [--check] [--diff [REF]] [--json]   the module map: each open item's
                 props.module (and props.modules_secondary) against the store's modules.yaml (a store without one
                 reads the registry config.json modules.store names); the view notes/modules_graph.md (beside the
                 store's board when it is not in notes/; per module its phase, status, items done and open, and
                 the gaps, and how many features and done items are placed; for an imported registry, the counts by
                 brick, the documents read and their divergences), written by brain sync; --check: the open items
                 with no module, or a module the registry does not know, and the imported entries' fields (exit 1),
                 then, as warnings, the features and done items with none (brain check warns of all of it);
                 --diff: what changed in the registry since its version at REF (default HEAD): modules added and
                 removed, document fields and hand fields changed;
                 under config.json views.strict, another engine than engine.pin writes nothing (--force)
"""


def cmd_modules(args, root: Path) -> int:
    """brain modules (brain.modules): the view printed, written with --write; --check: the module map's problems;
    --diff: what changed in the registry since a git ref."""
    store = _store(args, root)
    if not modules.applies(store, root):
        wanted = modules.named(root, store)
        raise SystemExit(f"brain modules: no {modules.REGISTRY} in {store} (the registry of modules)"
                         + (f", and config.json modules.store {wanted!r} names no store of the registry that keeps "
                            "one" if wanted else ""))
    if args.write and skew.refuse_view(root, "modules --write", args.force, f"the committed {modules.FILE}"):
        return 1
    if args.write:   # first, so --write --check writes the view and then checks the map
        view = _module_view(_project(args, root), root, store)
        print(f"view: {view} " + ("written" if modules.write(root, store, _store_label(root, store), view)
                                  else "unchanged"))
    if args.diff is not None:
        f = modules.registry_file(store, root)
        d = modules.diff(modules.at_ref(f, args.diff), modules.registry(store, root) or [])
        label = modules.registry_label(store, _store_label(root, store), root)
        if args.json and not args.check:
            print(json.dumps({"registry": label, "ref": args.diff, **d}, indent=1, ensure_ascii=False))
        else:
            print("\n".join(modules.diff_lines(d, label, args.diff)))
        if not args.check:
            return 0
    if args.check:
        found = modules.registry_problems(store, root) + modules.problems(store, root)
        more = modules.warnings(store, root)
        if args.json:
            print(json.dumps(found, indent=1))
        else:
            print("\n".join(found) or "module map: every open item placed")
            for line in more:   # the features and done items: told, never counted (wi-brain-module-backfill)
                print(f"warning: {line}")
        return 1 if found else 0
    if args.json:
        print(json.dumps(modules.data(store, root), indent=1, ensure_ascii=False, default=str))   # a YAML date
    elif not args.write:
        print(modules.render(store, _store_label(root, store), root), end="")
    return 0


def register(sub, ctx) -> None:
    mo = sub.add_parser("modules", help="the module map: each open item's module against the store's modules.yaml, "
                                        "the generated view notes/modules_graph.md")
    mo.add_argument("--write", action="store_true", help="write notes/modules_graph.md (brain sync does)")
    mo.add_argument("--force", action="store_true", help="--write even when the running engine is not config.json "
                                                         "engine.pin (refused under views.strict)")
    mo.add_argument("--check", action="store_true", help="the open items with no module or an unknown one, and the "
                                                         "imported entries' fields (exit 1)")
    mo.add_argument("--diff", nargs="?", const="HEAD", default=None, metavar="REF",
                    help="what changed in the registry since its version at the git ref REF (default HEAD): the "
                         "modules added and removed, the document fields and the hand fields changed")
    mo.add_argument("--json", action="store_true", help="the map as JSON (each module's counts, the problems); with "
                                                        "--check, the problems; with --diff, the changes")


run = cmd_modules
