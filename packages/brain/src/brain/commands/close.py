"""``brain close``: an item's definition of done in one command, from its merged PR (brain.closing)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import closing, features, graph, notes, paths
from ._common import _print_json, _project, _repos, _store

ORDER = 22   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 22   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain close ID --pr "repo #N" [--repo NAME] [--repo-dir D] [--outcome T] [--journal-title T] [--no-tidy] [--write]
                 [--json]   an item's definition of done from its merged PR, at zero token: the item closed with the
                 PR and its merge's date (the PR's title as the outcome), the journal's line, the features its title
                 or body names (feat-x: have) set, its changelog fragment checked, the milestones it leaves with no
                 open item listed with their trigger, its worktree and branch removed by brain tidy's plan, where the
                 PR's merge stands for the 24 h idle rule: a worktree no desktop-app session knows goes at once, the
                 head branch counts as merged when its tip is on the PR's head commit (squash or rebase merges);
                 kept, with why: an unmerged branch, a dirty, locked or leased worktree, one holding files git ignores
                 and would delete (.env, data: named), the one the shell stands in (the cd out of it is printed, then
                 the same command removes it); the plan, then --write (refused while the PR is not merged); --pr N
                 alone reads the repo of the current folder
"""


def _repo_dir(args, root: Path, name: str) -> tuple[str, Path | None, str]:
    """(the repo's name, its checkout, why none): --repo-dir, else the project's repo of that name, else the repo
    the current folder is in, else the project's only repo."""
    declared = [(r.name, r.path) for r in _repos(args, root)]
    if args.repo_dir:
        d = Path(args.repo_dir).resolve()
        return name or (paths.main_checkout(d) or d).name.lower(), d, ""
    if name:
        hit = next(((n, p) for n, p in declared if n.lower() == name.lower()), None)   # the project's spelling
        return (*hit, "") if hit else (name, None, f"{name}: no repo of that name in the project "
                                                   f"({', '.join(n for n, _ in declared) or 'none'})")
    here = paths.main_checkout(Path(os.getcwd()))
    for n, p in declared:
        if here is not None and paths.main_checkout(p) == here:
            return n, p, ""
    if len(declared) == 1:
        return declared[0][0], declared[0][1], ""
    return "", None, "--pr \"repo #N\" or --repo NAME: the current folder is in none of the project's repos"


def cmd_close(args, root: Path) -> int:
    try:
        name, number = closing.parse_ref(args.pr, args.repo or "")
    except closing.CloseError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 2
    name, repo_dir, why = _repo_dir(args, root, name)
    if repo_dir is None:
        print(f"brain: {why}", file=sys.stderr)
        return 2
    store = _store(args, root)
    try:
        pr = closing.read_pr(name, repo_dir, number)
        p = closing.plan(store, args.id, pr, repo_dir, outcome=args.outcome or "", do_tidy=not args.no_tidy)
    except (closing.CloseError, graph.GraphError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    if args.json and not args.write:
        _print_json(p.as_dict())
        return 1 if p.problems else 0
    if args.write and p.problems:
        print("\n".join(closing.render(p)))
        return 2
    written = None
    if args.write:
        try:
            written = closing.write(store, _project(args, root).journal, p, title=args.journal_title or "")
        except (graph.GraphError, features.FeatureError, notes.NotesError) as exc:
            print(f"brain: {exc} (what was written before it stays)", file=sys.stderr)
            return 1
    print("\n".join(closing.render(p, written)))
    return 1 if p.problems else 0


def register(sub, ctx) -> None:
    cl = sub.add_parser("close", help="an item's definition of done from its merged PR: closed, journal, features, "
                                      "fragment, milestones, tidy; the plan, then --write")
    cl.add_argument("id", help="the item")
    cl.add_argument("--pr", required=True, help='"repo #N" (a repo of the project), or N: the repo of the current '
                                                "folder (--repo NAME instead)")
    cl.add_argument("--repo", help="the repo of a bare --pr N")
    cl.add_argument("--repo-dir", help="the repo's checkout (default: the project's repo of that name)")
    cl.add_argument("--outcome", help="one line (default: the PR's title)")
    cl.add_argument("--journal-title", help="the title of today's journal entry when today has none "
                                            "(default: '<item> closed')")
    cl.add_argument("--no-tidy", action="store_true", help="leave the worktree and the branch")
    cl.add_argument("--write", action="store_true", help="apply the plan")
    cl.add_argument("--json", action="store_true", help="the plan as JSON (no --write)")


run = cmd_close
