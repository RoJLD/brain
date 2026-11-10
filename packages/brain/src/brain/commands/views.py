"""``brain views``: the generated views and their one writer (brain.views, docs/views.md): listed with where this
checkout stands; kept out of a branch's commit (--unstage) or put back at HEAD before a merge (--reset); written on
the default branch after each merge (--write, --commit).
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

from .. import actions, projects, skew, views
from ._common import _on_main, _project
from ._stores import _each_store, _merge_marks

ORDER = 285   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 135   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain views [--json]   the generated views (GENERATED in their first lines, or a _generated_ name: the kanban, the
                        roadmap, the plan and module maps, the decision queue, the audit, FEATURES.md, the graph's
                        _generated_*.yaml) git tracks, where this checkout stands (the default branch must hold them
                        fresh, brain check fails there on a stale one; a branch need not commit them), those changed
                        or staged here and those the merge driver kept from one side
  brain views --unstage | --reset   on a branch: the staged views taken out of the index after git add (the working
                        tree keeps them for the branch's checks), or every view put back at HEAD before git merge of
                        the default branch (then brain sync)
  brain views --write [--commit] [--no-audit] [--offline] [--force]   the one writer, after each merge, in a worktree
                        at the default branch's tip (never a main checkout): brain sync's writes, the audit view, then
                        brain check by the default branch's rules; the files it changed listed, and with --commit
                        committed alone (pushed and merged the project's way), never when HEAD lacks
                        origin/<default>'s tip (fetched unless --offline); another engine than config.json engine.pin
                        writes nothing
"""


def _audit_view(args, root: Path) -> int:
    """brain audit --write for the project at ``root`` when it keeps an audit view there (its lines but the
    ``view:`` one kept quiet); 0, else 1."""
    from .. import audit, cli
    project = _project(args, root)
    if args.no_audit or project.shares_root_with or not (root / audit.VIEW).is_file():
        return 0
    named = ["--project", project.name] if project.name in projects.load(root) else []   # at this root, a worktree's
    ns = cli.build_parser().parse_args(["--root", str(root), *named, "audit", "--write",
                                        *(["--force"] if args.force else [])])
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = audit.main(ns, root)
    except SystemExit as exc:
        print(f"brain views: {audit.VIEW} not written: {exc}")
        return 1
    for line in buf.getvalue().splitlines():
        if line.startswith("view: "):
            print(line)
    if code:
        print(f"brain views: {audit.VIEW} not written (brain audit exit {code})")
    return 1 if code else 0


def _tip_line(root: Path, where: views.Place) -> str:
    """A note when HEAD is not the default branch's tip: the views written are this branch's."""
    if not where.default:
        return "views: no default branch found (origin/HEAD, main or master): these views are this checkout's"
    head = actions.git(root, "rev-parse", "HEAD")
    tips = {actions.git(root, "rev-parse", "--verify", "-q", ref) for ref in (f"origin/{where.default}",
                                                                             where.default)} - {""}
    if head and head not in tips:
        return (f"views: HEAD is not {where.default}'s tip: these views are this branch's (the one writer runs in a "
                f"worktree at origin/{where.default})")
    return ""


def _write(args, root: Path) -> int:
    branch = _on_main(root)
    if branch:   # the services run from it, and the audit view is never written there
        raise SystemExit(f"brain: {root} is a main checkout on {branch}: write the views from a worktree at its tip "
                         f"(git worktree add -b chore/views-<date> <path> origin/{branch}, then brain --root <path> "
                         "views --write --commit)")
    if skew.refuse(root, "views --write", args.force):   # another engine than config.json engine.pin: nothing written
        return 1
    where = views.place(root)
    lacks = views.lacks_tip(root, where, fetch=not args.offline) if args.commit else ""
    note = _tip_line(root, where)
    if note:
        print(note)
    before = views.dirty(root)
    args.views_as_default = True   # its check is the one the default branch runs once this commit is merged
    rc = _each_store(args, root, sync=True, check=True)
    rc = _audit_view(args, root) or rc
    if not rc:
        _merge_marks(root, "regenerated", clear=True)
    written = sorted(views.dirty(root) - before)
    kept = [p for p in written if views.is_view(p, views.head_at(root, p))]
    print(f"views --write: {len(written)} file(s) changed ({len(kept)} view(s))"
          + "".join(f"\n  {p}" for p in written))
    if not args.commit or not written:
        return rc
    if rc:
        print("views --write: not committed: the check failed (fix it, then brain views --write --commit again)")
        return rc
    if lacks:   # views of a stale base: their PR would undo the later merges' views
        how = (f"git merge --ff-only {lacks}" if lacks != "the default branch" else
               "no default branch found (origin/HEAD, main or master)")
        print(f"views --write: not committed: HEAD lacks {lacks}'s tip, these views are a stale base's ({how}, then "
              f"{views.WRITER} --commit again)")
        return 1
    head = actions.git(root, "rev-parse", "--short", "HEAD")
    sha = views.commit(root, written, f"Views regenerated at {where.default or where.branch} {head} "
                                      f"({views.WRITER})")
    print(f"views --write: committed {sha}" if sha else "views --write: git refused the commit (git status says why)")
    return 0 if sha else 1


def cmd_views(args, root: Path) -> int:
    """brain views (brain.views): listed, --unstage, --reset, or --write (the one writer)."""
    if not args.write and (args.commit or args.no_audit or args.offline or args.force):
        raise SystemExit("brain views: --commit, --no-audit, --offline and --force go with --write")
    if args.unstage or args.reset:
        done = views.unstage(root) if args.unstage else views.reset(root)
        what = ("unstaged (the working tree keeps them; the commit leaves them as HEAD has them)" if args.unstage
                else "put back at HEAD (brain sync writes them again after the merge)")
        print(f"views: {len(done)} {what}" + "".join(f"\n  {p}" for p in done))
        return 0
    if args.write:
        return _write(args, root)
    return views.status(root, args.json)


def register(sub, ctx) -> None:
    vw = sub.add_parser("views", help="the generated views and their one writer: listed with where this checkout "
                                      "stands, --unstage or --reset on a branch, --write on the default branch "
                                      "after each merge")
    mode = vw.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="the one writer, in a worktree at the default branch's "
                                                           "tip: brain sync's writes, the audit view, brain check; "
                                                           "the files it changed listed")
    mode.add_argument("--unstage", action="store_true", help="on a branch: the staged views out of the index, after "
                                                             "git add (the working tree keeps them)")
    mode.add_argument("--reset", action="store_true", help="on a branch: every view back at HEAD, before git merge "
                                                           "of the default branch (then brain sync)")
    vw.add_argument("--commit", action="store_true", help="--write: commit the files it changed, alone (never when "
                                                          "HEAD lacks the default branch's tip)")
    vw.add_argument("--no-audit", action="store_true", help="--write: not the audit view (brain audit --write)")
    vw.add_argument("--offline", action="store_true", help="--write: no gh call nor fetch (the features' statuses "
                                                           "are not read, origin/<default> is not fetched)")
    vw.add_argument("--force", action="store_true", help="--write: write even when the running engine is not "
                                                         "config.json engine.pin")
    vw.add_argument("--json", action="store_true", help="the listing as JSON")


run = cmd_views
