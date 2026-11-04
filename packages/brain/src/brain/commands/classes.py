"""``brain classes``: every store's data class (config.json classes.stores) and where it may go (brain.classes)."""

from __future__ import annotations

from pathlib import Path

from .. import classes

ORDER = 240   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 280   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain classes [PATH...] [--check] [--json] [--suggest] [--matrix]   every store's data class (config.json
                 classes.stores: public, private, confidential, sealed, resident, secret, tenant:<id>), its tracked
                 files and the exits it takes; PATH: the store and class of each path; --check: exit 1 on a tracked
                 file or an engine store without a class, an exit its class forbids, tracked files its class keeps
                 out of the remote in clear, a class under its scope floor (waivers printed); --suggest: a starting
                 block to edit; --matrix: how each class may take each exit (brain.classes)
"""


def cmd_classes(args, root: Path) -> int:
    """Every store's data class and where it may go (brain.classes)."""
    return classes.main(root, check_only=args.check, as_json=args.json, which=args.paths, suggest_=args.suggest,
                        matrix_=args.matrix)


def register(sub, ctx) -> None:
    cl = sub.add_parser("classes", help="every store's data class (config.json classes.stores) and where it may go "
                                        "(brain.classes)")
    cl.add_argument("paths", nargs="*", metavar="PATH", help="the store and class of each path (a repo path, "
                    "$BRAIN_HOME/... or ~/...)")
    cl.add_argument("--check", action="store_true", help="exit 1 on a store without a class or a destination its "
                                                         "class forbids")
    cl.add_argument("--json", action="store_true", help="stable keys")
    cl.add_argument("--suggest", action="store_true", help="a starting classes block for config.json, to edit")
    cl.add_argument("--matrix", action="store_true", help="how each class may take each exit")


run = cmd_classes
