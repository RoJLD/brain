"""``brain lesson`` (alias: brain lessons): the lessons of the graph: list (bare), --follow their lineage, add, seen,
rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import graph, lessons, projects
from ._common import _project, _scope, _store, _whole

ORDER = 410   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 330   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain lesson [--follow] [--status S] [--signal S] [--json]   (also: brain lessons) the lessons of the graph
                 (nodes/lessons.yaml): status, seen, severity, signal, fix; --follow: each one's lineage (learned
                 from, led to, its PR, enforced by, recurred since its fix) and the friction per item by week
  brain lesson add les-ID --title T --trigger T --anti-pattern A --check C [--severity high|medium|low]
                 [--signal merges|guards|tests|waits|tokens|owner|rework|other] [--from NODE]... [--pr "repo #N"]
                 [--rule Σ-NAME] [--led-to ITEM] [--enforced-by NODE]... [--why-not-script W] [--new]
                 refused when it is close to a known lesson (brain lesson seen instead); a severe one nothing fixes
                 files its item proposal (priority_proposed)
  brain lesson seen ID (--from NODE | --pr "repo #N")   one more occurrence; seen twice (once if severe) with no
                 fix, or recurring after its fix (regressed), it files an item proposal led_to it
  brain lesson rules [--all] [--repo NAME] [--top N] [--json]   the iron rules (Σ-NAME, Sigma-NAME) cited in each
                 registered repo's tracked Markdown, read only, with the lessons that restate them
"""


def cmd_lesson(args, root: Path) -> int:
    """brain lesson [add|seen|list|rules] (brain.lessons); bare, or brain lessons: the list, --follow the lineage."""
    sub_cmd = getattr(args, "lesson_cmd", None) or "list"
    if sub_cmd == "rules":
        return _lesson_rules(args, root)
    store = _store(args, root)
    if sub_cmd == "list":
        return _lesson_list(args, store)
    try:
        if sub_cmd == "add":
            out = lessons.add(store, args.id, args.title, trigger=args.trigger, anti_pattern=args.anti_pattern,
                              check=args.check, severity=args.severity, signal=args.signal, frm=args.frm,
                              prs=args.pr or "", rule=args.rule or "", led_to=args.led_to or "",
                              enforced_by=args.enforced_by, why_not_script=args.why_not_script or "",
                              source=args.source or "", status=args.status or "", new=args.new)
        else:
            out = lessons.seen(store, args.id, frm=args.frm, pr=args.pr or "")
    except (lessons.LessonError, graph.GraphError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    _lesson_said(sub_cmd, out)
    return 0


def _lesson_said(sub_cmd: str, out: dict) -> None:
    node = out["node"]
    print(f"{sub_cmd}: {node['id']} [{node['status']}] seen {lessons.seen_of(node)}"
          + (", regressed after its fix" if out.get("regressed") else "") + "; then brain sync and brain check")
    if out.get("filed"):
        print(f"filed {out['filed']} (priority_proposed, led_to from {node['id']}): the fix to choose, a script "
              "first; wi-brain-ideation-board turns these into ideas once it exists")
    if out.get("linked"):
        print(f"linked {node['id']} led_to {out['linked']}: an open item close to it carries the fix (brain item "
              "unlink to undo)")


def _lesson_list(args, store: Path) -> int:
    rs = lessons.select(lessons.rows(store), args.status or "", args.signal or "") \
        if (store / lessons.FILE).is_file() else []
    if args.json:
        print(json.dumps({"lessons": rs, "friction": lessons.friction(store)}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(lessons.render_follow(rs, lessons.friction(store)) if args.follow
                        else lessons.render_list(rs)))
    return 0


def _lesson_rules(args, root: Path) -> int:
    repos = [r for p in _scope(args, root) for r in projects.repos_of(p)]
    if args.repo:
        repos = [r for r in repos if r.name in args.repo]
        if not repos:
            raise SystemExit(f"brain lesson rules: no registered repo named {', '.join(args.repo)}")
    try:
        store = lessons.store_of(_project(args, root))
    except lessons.LessonError:
        store = None
    index = lessons.iron_rules(repos, lessons.rule_links(store))
    print(json.dumps(index, ensure_ascii=False, indent=1) if args.json
          else "\n".join(lessons.render_rules(index, args.top)))
    return 0


def register(sub, ctx) -> None:
    le = sub.add_parser("lesson", aliases=["lessons"],
                        help="the lessons of the graph: list (bare), --follow their lineage, add, seen, rules")
    le.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    le.add_argument("--follow", action="store_true", help="each lesson's lineage and the friction per item by week")
    le.add_argument("--status", choices=lessons.STATUSES)
    le.add_argument("--signal", choices=lessons.SIGNALS)
    le.add_argument("--json", action="store_true")
    les = le.add_subparsers(dest="lesson_cmd")
    lsl = les.add_parser("list", help="the lessons (the same as bare brain lesson)")
    lsl.add_argument("--follow", action="store_true", default=argparse.SUPPRESS)
    lsl.add_argument("--status", choices=lessons.STATUSES, default=argparse.SUPPRESS)
    lsl.add_argument("--signal", choices=lessons.SIGNALS, default=argparse.SUPPRESS)
    lsl.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    la = les.add_parser("add", help="a new Lesson node; refused when close to a known one (brain lesson seen)")
    la.add_argument("id", help="les-<project>-<slug>")
    la.add_argument("--title", required=True)
    la.add_argument("--trigger", required=True, help="the situation it happens in")
    la.add_argument("--anti-pattern", required=True, help="what went wrong")
    la.add_argument("--check", required=True, help="how to tell it happened again: a command in backticks, a test, "
                                                   "a guard's refusal")
    la.add_argument("--severity", default="medium", choices=lessons.SEVERITIES)
    la.add_argument("--signal", default="other", choices=lessons.SIGNALS, help="the friction signal it shows in")
    la.add_argument("--from", dest="frm", action="append", help="learned_from: the item, ADR, DDR or session "
                                                                 "(repeatable)")
    la.add_argument("--pr", help='the PR(s) it was seen in, e.g. "my-brain #185, #194"')
    la.add_argument("--rule", help="the iron rule it restates (Σ-NAME)")
    la.add_argument("--led-to", help="the item that fixes it")
    la.add_argument("--enforced-by", action="append", help="the hook, test or workflow node that checks it "
                                                           "(repeatable; the lesson is then enforced)")
    la.add_argument("--why-not-script", help="why no script can check it")
    la.add_argument("--source", help="where it was written down first (a memory note, a hand-over note)")
    la.add_argument("--status", choices=lessons.STATUSES, help="default: enforced with --enforced-by, else open")
    la.add_argument("--new", action="store_true", help="add it even when close to a known lesson")
    lse = les.add_parser("seen", help="one more occurrence of a known lesson")
    lse.add_argument("id")
    lse.add_argument("--from", dest="frm", action="append", help="the item, ADR, DDR or session it recurred in")
    lse.add_argument("--pr", help="the PR it recurred in")
    lru = les.add_parser("rules", help="the iron rules cited in each registered repo's tracked Markdown (read only)")
    lru.add_argument("--all", action="store_true", help="every registered project's repos")
    lru.add_argument("--repo", action="append", help="one repo of the registry (repeatable)")
    lru.add_argument("--top", type=_whole, default=0, help="rules shown per repo (default: all)")
    lru.add_argument("--json", action="store_true")


run = cmd_lesson
