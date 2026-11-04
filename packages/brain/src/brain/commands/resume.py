"""``brain resume``: the resume pack: the project's present state, stable to volatile, at zero token (on demand; the
SessionStart hook says how old the written one is).
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import resume
from ._common import _scope

ORDER = 300   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 310   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain resume [--project P | --all] [--budget N] [--write] [--offline] [--health] [--notes DIR]...
                 the resume pack: the project's present state from the graph, records, journal and git, ordered from
                 stable to volatile (milestones, frontier and P0/P1, decisions, open PRs, journal, hand-over notes,
                 then the date); --budget cuts from the volatile end (default 3000 tokens, 0: no limit); --write
                 keeps it in <BRAIN_HOME>/resume/<project>.md, whose age the SessionStart hook reports in one line
"""


def cmd_resume(args, root: Path) -> int:
    """The resume pack of the project (a worktree of a registered checkout keeps the project's name), or of every
    registered project with --all; printed, and kept in <BRAIN_HOME>/resume/<project>.md with --write."""
    scope = _scope(args, root) if args.all else [getattr(args, "project_obj", None) or resume.project_for(root)]
    texts = []
    for p in scope:
        if not p.root.is_dir():
            print(f"== {p.name}: {p.root} not found, skipped", file=sys.stderr)
            continue
        text = resume.build(p, budget=args.budget, offline=args.offline, health=args.health, notes=args.notes)
        if args.write:
            out = resume.write(p.name, text)
            print(f"resume: {p.name} -> {out} (~{resume.tokens(text)} tokens)", file=sys.stderr)
        texts.append(text)
    print("\n".join(texts), end="")
    return 0


def register(sub, ctx) -> None:
    rs = sub.add_parser("resume", help="the resume pack: the project's present state, stable to volatile, at zero "
                                       "token (on demand; the SessionStart hook says how old the written one is)")
    rs.add_argument("--all", action="store_true", help="every project of the registry, one pack each")
    rs.add_argument("--budget", type=int, default=resume.BUDGET,
                    help=f"tokens (~{resume.CHARS_PER_TOKEN} characters each), cut from the volatile end; 0: no limit "
                         f"(default {resume.BUDGET})")
    rs.add_argument("--write", action="store_true", help="also keep it in <BRAIN_HOME>/resume/<project>.md")
    rs.add_argument("--offline", action="store_true", help="do not ask gh for the open PRs")
    rs.add_argument("--health", action="store_true", help="check the project's stacks (~1 s each at most)")
    rs.add_argument("--notes", action="append", help="a folder of hand-over notes to read first (repeatable; "
                                                     "defaults: $BRAIN_NOTES, else <BRAIN_HOME>/handover and the "
                                                     "desktop app's session-group notes folders)")
    rs.add_argument("--hook", action="store_true", help="SessionStart hook: hook JSON on stdin, one line saying "
                                                        "whether the pack is written and how old it is")


def early(args) -> int | None:
    if args.hook:  # a hook: never fails, one line
        return resume.hook_main(["SessionStart"])
    return None


run = cmd_resume
