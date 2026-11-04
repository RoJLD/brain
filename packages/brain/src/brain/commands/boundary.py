"""``brain boundary``: every tracked file's side by boundary.yaml (engine, personal, claude, generated) and the
readiness of the engine side.
"""

from __future__ import annotations

from pathlib import Path

from .. import boundary

ORDER = 220   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 260   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain boundary [--check] [--side engine|personal|claude|generated] [--readiness] [--json]   every tracked file's
                 side by boundary.yaml (engine: leaves for the public engine repo, at its target), and the readiness
                 of the engine side: the terms of config.json public.deny found in its files; --check: exit 1 on a
                 file no rule classifies; --side: that side's files; --readiness: the hits per file
"""


def cmd_boundary(args, root: Path) -> int:
    """Every tracked file's side by boundary.yaml, and the readiness of the engine side (brain.boundary)."""
    return boundary.main(root, check=args.check, side=args.side or "", detail=args.readiness, as_json=args.json)


def register(sub, ctx) -> None:
    bd = sub.add_parser("boundary", help="every tracked file's side by boundary.yaml (engine, personal, claude, "
                                         "generated) and the readiness of the engine side")
    bd.add_argument("--check", action="store_true", help="exit 1 on a file no rule classifies, an engine rule "
                                                         "without a target or two files with one target")
    bd.add_argument("--side", choices=boundary.SIDES, help="list that side's files (engine: with their target)")
    bd.add_argument("--readiness", action="store_true", help="the denied terms found per engine file")
    bd.add_argument("--json", action="store_true", help="stable keys")


run = cmd_boundary
