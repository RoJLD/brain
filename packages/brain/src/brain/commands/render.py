"""``brain render``: the neutral source (source/) written as an agent's own files: claude (the marketplace, byte for
byte), agents (AGENTS.md, .agents/skills), cursor, gemini, antigravity, grok, hermes (brain.render).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import neutral, paths, projects, render, skew

ORDER = 230   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 270   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain render [--target claude|agents|cursor|gemini|antigravity|grok|hermes] [--project P] [--repo DIR] [--out DIR]
                 [--write | --check] [--force] [--json]   the neutral source (source/: rules with scope and id,
                 procedures, MCP servers, packs) written as an agent's own files: claude, the marketplace and its
                 plugins in the brain's repo (byte for byte the hand-written step 1; no marker, brain check refuses a
                 hand edit); agents, the project's AGENTS.md (its chain flattened: global, ancestors, its CLAUDE.md
                 last) and .agents/skills; cursor, gemini, antigravity, grok and hermes, the base plus each tool's MCP
                 settings (JSON merged, never replaced); no flag: the plan; --write: into the brain's and the
                 project's repo (never a production checkout, never the home folder; --force replaces a file it did
                 not write); --check: exit 1 when an output is not current; --out: a dry render into a folder
"""


def cmd_render(args, root: Path) -> int:
    """``brain render``: the neutral source written as an agent's own files (brain.render). The brain is the one with
    the neutral source (--root, the repo here, else config.json's); the project is --project, else the one here."""
    base = neutral.brain_root(Path(args.root).resolve() if args.root else None)
    obj = getattr(args, "project_obj", None)
    if obj is None and args.target != "claude":
        here = projects.for_root(paths.find_root())
        obj = here if here.registered else None
        if obj is None:
            print("brain render: name the project to render for (--project; brain projects lists them)",
                  file=sys.stderr)
            return 2
    project_root = Path(args.repo).resolve() if args.repo else (obj.root if obj else None)
    if args.write and not args.out and skew.refuse(base, "render", args.force):   # another engine than the pin
        return 1
    return render.main(base, args.target, project=obj.name if obj else None, project_root=project_root,
                       out=Path(args.out).resolve() if args.out else None, do_write=args.write, check=args.check,
                       force=args.force, as_json=args.json)


def register(sub, ctx) -> None:
    rd = sub.add_parser("render", help="the neutral source (source/) written as an agent's own files: claude (the "
                                       "marketplace, byte for byte), agents (AGENTS.md, .agents/skills), cursor, "
                                       "gemini, antigravity, grok, hermes (brain.render)")
    rd.add_argument("--target", choices=render.TARGETS, default="claude", help="the agent (default claude)")
    rd.add_argument("--project", default=argparse.SUPPRESS, help="the project to render for (same as brain --project; "
                                                                 "default: the one here)")
    rd.add_argument("--repo", help="the project's checkout to write into, a worktree of it (default: its root)")
    rd.add_argument("--out", help="render into this folder instead: a dry run to look at")
    rdm = rd.add_mutually_exclusive_group()
    rdm.add_argument("--write", action="store_true", help="write what is not current, remove stray files")
    rdm.add_argument("--check", action="store_true", help="exit 1 when an output is not current")
    rd.add_argument("--force", action="store_true", help="with --write: replace a file brain render did not write, "
                                                         "and write even when the running engine is not config.json "
                                                         "engine.pin")
    rd.add_argument("--json", action="store_true", help="stable keys")


run = cmd_render
