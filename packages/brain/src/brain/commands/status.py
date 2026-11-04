"""``brain status``: each project's indicators at zero token: items, frontier, decisions, milestones, audit, stacks,
code index, journals, records, ledgers.
"""

from __future__ import annotations

from pathlib import Path

from .. import status
from ._common import _scope

ORDER = 130   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 210   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain status [--all] [--quick] [--json]   each project's indicators at zero token: items by status and priority,
                 the frontier, decisions waiting on {owner}, milestones, audit debt, stacks, code index, its open
                 alerts (brain alerts), journals, records and ledgers; --all adds the totals and the ids shared across
                 stores; --quick reads the files only (no audit, stack, code index or scheduler probe)
"""


def cmd_status(args, root: Path) -> int:
    """Each project's indicators (brain.status): the project here or --project's, or every one with --all."""
    data = status.run(_scope(args, root), every=args.all, quick=args.quick, root=root)
    print(status.render_json(data) if args.json else "\n".join(status.render(data)))
    return 0


def register(sub, ctx) -> None:
    stt = sub.add_parser("status", help="each project's indicators at zero token: items, frontier, decisions, "
                                        "milestones, audit, stacks, code index, journals, records, ledgers")
    stt.add_argument("--all", action="store_true", help="every registered project, the totals and the ids shared "
                                                        "across stores")
    stt.add_argument("--quick", action="store_true", help="the files only: no audit, stack or code index probe")
    stt.add_argument("--json", action="store_true", help="stable keys, no timestamp")


run = cmd_status
