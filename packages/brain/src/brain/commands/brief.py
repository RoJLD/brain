"""``brain brief``: a sub-session's brief written from the graph (the coordinator edits only what needs judgement)."""

from __future__ import annotations

import json
from pathlib import Path

from ._common import _project

ORDER = 520   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 180   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain brief ITEM [--class trivial|standard|strategic] [--budget 400k] [--coordinator ID] [--notes DIR] [--write F]
                        a sub-session's brief from the graph: the item, its decided props and open questions, its
                        subgraph, its specs and ADRs, its files and collisions, the class's model and effort
                        (config.json brief.classes), the budget, the cost estimate, the coordinator's id (--coordinator,
                        else $CLAUDE_CODE_HOST_SESSION_ID), the shared notes folder, and the definition of done and
                        the never-list read from {owner}'s rules
"""


def cmd_brief(args, root: Path) -> int:
    """brain brief ITEM (brain.brief): the brief printed, and written with --write."""
    from .. import brief
    try:
        b = brief.build(_project(args, root), args.item, task_class=args.task_class, budget=args.budget,
                        coordinator=args.coordinator, notes=args.notes)
    except brief.BriefError as exc:
        raise SystemExit(f"brain brief: {exc}") from None
    text = json.dumps(b.as_dict(), indent=2, ensure_ascii=False) if args.json else brief.render(b)
    if args.write:
        Path(args.write).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def register(sub, ctx) -> None:
    br = sub.add_parser("brief", help="a sub-session's brief written from the graph (the coordinator edits only "
                                      "what needs judgement)")
    br.add_argument("item")
    br.add_argument("--class", dest="task_class", default="standard", help="trivial, standard (default) or strategic: "
                                                                            "the model and effort (brief.classes)")
    br.add_argument("--budget", default="", help="the context budget (400k, 600k, 800k, 1M; default: the class's)")
    br.add_argument("--coordinator", default="", help="the coordinator's app session id (default: "
                                                      "$CLAUDE_CODE_HOST_SESSION_ID)")
    br.add_argument("--notes", default="", help="the shared notes folder (default: the desktop app's for the "
                                                "coordinator, when it exists)")
    br.add_argument("--write", default="", help="also write the brief to this file")
    br.add_argument("--json", action="store_true")


run = cmd_brief
