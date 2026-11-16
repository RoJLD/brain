"""``brain lint``: lint the owner's rules at zero token."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import formatlint, lessons, lint, resume
from ..inventory import AuditError, git
from ._common import _now, _queue_changed, _scope, _store

ORDER = 400   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 320   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain lint rules [--project P | --all] [--json] [--propose [--max N] [--dry-run]]
                 at zero token: the tokens injected per session (global rules against the 10,000-character hook cap,
                 CLAUDE.md files, memory index, skill descriptions), duplicates between rule files, procedures
                 (script candidates), rules a hook could check (guard candidates), the hard-rule ratio (enforced_by);
                 --propose files one DDR per candidate rule or pair, at most N (8) rules-lint DDRs pending at once;
                 exit 1 when the injected rules pass the hook cap
  brain lint lessons [--json] [--propose]   the open lessons nothing enforces: a guard candidate when their check
                 is a command (scripts before rules; --propose files its item), else a prose lesson to justify
                 (props.why_not_script)
  brain lint formats [--repo-dir D] [--backend python|ast-grep | --compare] [--json]   the format lints over a
                 repo's Python files: a path into the brain's home built outside brain.paths, a file of the home
                 written around brain.stateio, a test reading the real home; --compare runs the python and the
                 ast-grep backends and prints what each finds that the other does not, and how long each took
                 (ast-grep N/A without its pinned binary); whatever config.json's switches (brain.formatlint)
"""


def cmd_lint(args, root: Path) -> int:
    """``brain lint rules``: the report for the project of the current folder (a worktree keeps its project's name),
    a registered one, or every one; --propose files the next batch of DDRs in this repo's queue. ``brain lint
    lessons``: brain.lessons' linter on the project's store."""
    if args.lint_cmd == "lessons":
        return _lint_lessons(args, root)
    scope = _scope(args, root) if args.all else [getattr(args, "project_obj", None) or resume.project_for(root)]
    report = lint.lint([p for p in scope if p.root.is_dir()])
    lint.mark_asked(report, root)
    filed = None
    if args.propose:
        filed = lint.propose(root, report, at=args.at or _now(), limit=args.max, session=args.session or "",
                             dry_run=args.dry_run)
        if filed["filed"] and not args.dry_run:
            lint.mark_asked(report, root)
    if args.json:
        out = lint.to_json(report)
        if filed is not None:
            out["proposed"] = filed
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print("\n".join(lint.render(report)))
        if filed is not None:
            verb = "would file" if args.dry_run else "filed"
            print(f"propose: {verb} {len(filed['filed'])} DDR(s) ({filed['pending_before']} rules-lint DDR(s) "
                  f"already pending, at most {filed['limit']} at once; {filed['left']} left for a later batch)")
            for f in filed["filed"]:
                print(f"  {f['id']}: {f['title']}")
    if filed and filed["filed"] and not args.dry_run:
        _queue_changed(root, args)
    return 1 if lint.over_cap(report) else 0


def early(args) -> int | None:
    """``brain lint formats`` reads a repo, any repo: no brain root needed (the other subcommands need one)."""
    return _lint_formats(args) if args.lint_cmd == "formats" else None


def _lint_formats(args) -> int:
    """``brain lint formats``: one backend, or both compared, over the repo of --repo-dir (the current folder)."""
    try:
        top = Path(git(Path(args.repo_dir or Path.cwd()).resolve(), "rev-parse", "--show-toplevel").strip())
    except AuditError as exc:
        print(f"brain lint formats: {exc}", file=sys.stderr)
        return 2
    report = formatlint.run(top, list(formatlint.BACKENDS) if args.compare else [args.backend])
    diff = formatlint.compare(report)
    if args.json:
        rows = {b: {"seconds": r["seconds"], "why": r["why"], "hits": [vars(h) for h in r["hits"]]}
                for b, r in report.items()}
        print(json.dumps({"repo": str(top), "backends": rows,
                          "diff": {k: [vars(h) for h in v] for k, v in diff.items()}}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(formatlint.render(report, diff)))
    return 0


def _lint_lessons(args, root: Path) -> int:
    store = _store(args, root)
    if not (store / lessons.FILE).is_file():
        print(f"lessons: none in {store} yet (brain lesson add)")
        return 0
    found = lessons.lint_lessons(store)
    got = lessons.propose_guards(store, found) if args.propose else {"filed": [], "linked": []}
    if args.json:
        print(json.dumps({"findings": found, **got}, ensure_ascii=False, indent=1))
        return 0
    print("\n".join(lessons.render_lint(found)))
    for nid in got["filed"]:
        print(f"  filed {nid} (priority_proposed); then brain sync and brain check")
    for nid in got["linked"]:
        print(f"  linked to {nid}, an open item close to the lesson (led_to); then brain sync and brain check")
    return 0


def register(sub, ctx) -> None:
    who = ctx.who
    li = sub.add_parser("lint", help=f"lint {who}'s rules at zero token").add_subparsers(dest="lint_cmd",
                                                                                         required=True)
    lr = li.add_parser("rules", help="tokens injected per session, duplicates, script and guard candidates, hard "
                                     "rules (enforced_by); exit 1 when the injected rules pass the hook cap")
    lr.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    lr.add_argument("--all", action="store_true", help="every project of the registry, compared with each other")
    lr.add_argument("--json", action="store_true")
    lr.add_argument("--propose", action="store_true", help="file the next batch of candidates as DDRs in this repo's "
                                                           "decision queue, the most useful first")
    lr.add_argument("--max", type=int, default=lint.MAX_PENDING,
                    help=f"rules-lint DDRs pending at once at most (default {lint.MAX_PENDING})")
    lr.add_argument("--dry-run", action="store_true", help="with --propose: say what would be filed")
    lr.add_argument("--session", help="the asking session's id")
    lr.add_argument("--at", help="time asked (default: now)")
    ll = li.add_parser("lessons", help="the open lessons nothing enforces: guard candidates (their check is a "
                                       "command) and prose lessons to justify (why_not_script)")
    lf = li.add_parser("formats", help="the format lints over a repo (brain.formatlint): one backend, or the python "
                                       "and ast-grep ones compared")
    lf.add_argument("--repo-dir", metavar="D", help="the repo read (default: the current folder's)")
    how = lf.add_mutually_exclusive_group()
    how.add_argument("--backend", choices=formatlint.BACKENDS, default="python", help="the backend (default python)")
    how.add_argument("--compare", action="store_true", help="both backends: what each finds that the other does not, "
                                                           "and their times")
    lf.add_argument("--json", action="store_true")
    ll.add_argument("--json", action="store_true")
    ll.add_argument("--propose", action="store_true", help="file the item proposal of each guard candidate no open "
                                                           "item fixes yet")


run = cmd_lint
