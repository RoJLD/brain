"""``brain rules diff``: the owner's rules compared across this machine's CLAUDE.md, the brain's global rules, the
project's CLAUDE.md and the feedback memory notes, read only (brain.rulesdiff)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import config, projects, rulesdiff

ORDER = 401   # its place in brain --help's list of commands (brain.commands), after brain lint
USAGE_ORDER = 321   # its usage lines' place in brain --help's epilog, after brain lint's
USAGE = """\
  brain rules diff [--project P] [--json] [--subjects FILE] [--machine-rules FILE] [--global FILE]...
                 [--project-rules FILE]... [--notes DIR]... [--restricted-notes DIR]...
                 read only, at zero token: the rule units of ~/.claude/CLAUDE.md, the brain's global rules
                 (config.json rules), the project's CLAUDE.md and the machine's feedback memory notes, classed
                 identical, near (brain lint rules' measure), one side, and, with a subject list (config.json
                 rules_diff.subjects or --subjects), contradictory (one subject and scope, two values) and to check;
                 the restricted notes (rules_diff.restricted) by name and subjects only; exit 2 when a file named
                 by a flag cannot be read
"""


def early(args) -> int:
    """``brain rules diff``: before any root is resolved (a repo with no graph store has rules too)."""
    cfg = config.load()
    project = projects.get(args.project) if getattr(args, "project", None) else None
    if args.root:
        project_dir = Path(args.root).resolve()
    else:
        project_dir = rulesdiff.project_root(project, Path.cwd())

    def paths(values):
        return [Path(v).expanduser() for v in values] if values else None

    try:
        report = rulesdiff.build(cfg, project_dir, machine=Path(args.machine_rules).expanduser()
                                 if args.machine_rules else None,
                                 global_rules=paths(args.global_rules), project_rules=paths(args.project_rules),
                                 notes=paths(args.notes), subjects=Path(args.subjects).expanduser()
                                 if args.subjects else None,
                                 restricted=paths(args.restricted_notes))
    except rulesdiff.RulesDiffError as exc:
        print(f"brain rules diff: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rulesdiff.to_json(report), ensure_ascii=False, indent=1))
    else:
        print("\n".join(rulesdiff.render(report)))
    return 0


def register(sub, ctx) -> None:
    ru = sub.add_parser("rules", help=f"{ctx.who}'s rules across their sources: diff (read only)")
    rus = ru.add_subparsers(dest="rules_cmd", required=True)
    d = rus.add_parser("diff", help="the rule units of each source classed identical, near, one side, "
                                    "contradictory, to check (read only)")
    d.add_argument("--json", action="store_true", help="each unit's source, line, class, subject and value")
    d.add_argument("--subjects", metavar="FILE",
                   help="the subject list, YAML (default: config.json rules_diff.subjects)")
    d.add_argument("--machine-rules", metavar="FILE", help="instead of ~/.claude/CLAUDE.md")
    d.add_argument("--global", dest="global_rules", metavar="FILE", action="append",
                   help="instead of the brain's global rules (config.json rules); repeatable")
    d.add_argument("--project-rules", metavar="FILE", action="append",
                   help="instead of the project's CLAUDE.md files; repeatable")
    d.add_argument("--notes", metavar="DIR", action="append",
                   help="a memory folder instead of every project's on this machine; repeatable")
    d.add_argument("--restricted-notes", metavar="DIR", action="append",
                   help="a restricted memory folder, read for note names and subjects only, instead of "
                        "config.json rules_diff.restricted; repeatable")
