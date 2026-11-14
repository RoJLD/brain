"""``brain resources``: what runs for the Brain costs on this machine (CPU, memory, disk, network, the sessions'
processes, the containers, the stores, the tokens today and the quota), at zero token (brain.resources).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import resources, resources_view

ORDER = 271   # its place in brain --help's list of commands (brain.commands): after profile
USAGE_ORDER = 255   # its usage lines' place in brain --help's epilog, after brain profile's
USAGE = """\
  brain resources [--by machine|project|session|container|store] [--quick] [--json]   what runs for the Brain
                 costs on this machine, at zero token (brain.resources): the CPU, the committed memory, the free
                 space of the Brain's drives and Temp, the network's throughput up and down; each Claude Code CLI's
                 memory and process tree tied to its session, with its tokens today; the brain commands and the test
                 suites running; the containers (docker stats, bounded; Docker down is said, not an error) and the
                 stack that declares each; the stores' sizes under BRAIN_HOME; the tokens today, the quota's pace and
                 the room left in session-hours; WARN at 85 %, CRITICAL at 95 %; --by: one section; --quick: no
                 docker stats and no folder walked; --project P: that project's sessions and containers. The
                 process rows need psutil (the tui extra); without it the machine's totals come from the standard
                 library. brain tui shows the same sampler's band at the top right
"""


def cmd_resources(args, root: Path) -> int:
    """The full sample, or one section of it, as text or JSON; exit 1 when the sample fails."""
    sampler = resources.Sampler(root, project=getattr(args, "project", None) or None)
    try:
        doc = sampler.sample(docker=not args.quick, walks=not args.quick)
    except Exception as exc:   # said and exit 1: the command never prints a traceback for a machine it cannot read
        print(f"brain resources: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.by:
        doc = resources_view.section(doc, args.by)
    print(json.dumps(doc, ensure_ascii=False, indent=1) if args.json else "\n".join(resources_view.render(doc)))
    return 0


def register(sub, ctx) -> None:
    rs = sub.add_parser("resources", help="what runs for the Brain costs on this machine: CPU, memory, disk, network, "
                                          "the sessions' processes, the containers, the stores, the tokens today and "
                                          "the quota (zero token)")
    rs.add_argument("--by", choices=tuple(resources_view.SECTIONS),
                    help="one section: the machine (with the tokens, the quota and the overhead), the projects, the "
                         "sessions, the containers or the stores")
    rs.add_argument("--quick", action="store_true", help="no docker stats and no folder walked (the stores' sizes)")
    rs.add_argument("--json", action="store_true", help="the sample as JSON")


run = cmd_resources
