"""``brain merge-ready <pr>``: the merge gate's question at zero token: exit 0 (and a stamp for the head) or the list
of what blocks (brain.mergeready).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..inventory import AuditError

ORDER = 502   # its place in brain --help's list of commands (brain.commands), after merge-check
USAGE_ORDER = 161
USAGE = """\
  brain merge-ready PR [--repo-dir D] [--slug OWNER/NAME] [--remote R] [--no-fetch] [--json]   the merge gate: the
                        PR open and not a draft; the base and its head fetched again, main not moved under a file the
                        PR touches; brain merge-check on the head against that merge base; every CI check green on it;
                        the review's stamp for the head with no finding open; for a public repo, the public check's
                        stamp; nothing private in the PR's title and body. Exit 0, a stamp under
                        <BRAIN_HOME>/merge-ready and the head to merge (gh pr merge --match-head-commit), else exit 1
                        and what blocks (2: gh or git failed)
  brain merge-ready PR --with PR... [--test] [--python P] [...]   the PRs merged together, in that order: each
                        through the gate alone, then integrated on the base by git merge-tree with the repo's merge
                        driver (nothing checked out; a head that conflicts left out), the merge order said, and each
                        PR GitHub will see conflicting once those before it merge (a new head needed: not ready, no
                        stamp); the tests brain impact chooses for the set, run by --test in a scratch worktree; a
                        stamp per head ready as it is; exit 0 when the whole set is ready
"""


def _ids(values) -> list[str]:
    return [v.strip() for x in values or [] for v in str(x).split(",") if v.strip()]


def _together(args, top: Path) -> int:
    from .. import mergeready, mergetogether
    prs = list(dict.fromkeys([str(args.pr), *_ids(args.with_)]))
    try:
        t = mergetogether.check(top, prs, args.slug or "", args.remote or "", fetch=not args.no_fetch,
                                test=args.test, python=args.python or "", project=getattr(args, "project", "") or "")
    except (AuditError, mergeready.GateError) as exc:
        print(f"brain merge-ready: {exc}", file=sys.stderr)
        return 2
    try:
        written = [str(f) for f in mergetogether.stamps(t)]
    except OSError as exc:
        print(f"brain merge-ready: a stamp was not written: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({**t.to_json(), "stamps": written}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(mergetogether.lines(t)))
        for f in written:
            print(f"stamp: {f}")
    return 0 if t.ready else 1


def _set(args) -> int:
    """--with's path: PRs merged together; --test and --python alone are refused."""
    from .merge_check import git_top
    if not args.with_:
        print("brain merge-ready: --test and --python go with --with PR (a set of PRs merged together)",
              file=sys.stderr)
        return 2
    try:
        return _together(args, Path(git_top(Path(args.repo_dir or ".").resolve())))
    except AuditError as exc:
        print(f"brain merge-ready: {exc}", file=sys.stderr)
        return 2


def early(args) -> int:
    """Any checkout of the PR's repo (a worktree too); gh reads the PR."""
    from .. import mergeready
    from .merge_check import git_top
    if args.with_ or args.test or args.python:
        return _set(args)
    try:
        top = Path(git_top(Path(args.repo_dir or ".").resolve()))
        g = mergeready.gate(top, args.pr, args.slug or "", args.remote or "", fetch=not args.no_fetch,
                            view=mergeready.gh_view)
    except (AuditError, mergeready.GateError) as exc:
        print(f"brain merge-ready: {exc}", file=sys.stderr)
        return 2
    out = g.to_json()
    if g.ready:
        try:
            out["stamp"] = str(mergeready.stamp(g))
        except OSError as exc:
            print(f"brain merge-ready: ready, but the stamp was not written: {exc}", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print("\n".join(mergeready.lines(g)))
        if g.ready:
            print(f"stamp: {out['stamp']}")
    return 0 if g.ready else 1


def register(sub, ctx) -> None:
    mr = sub.add_parser("merge-ready", help="the merge gate: exit 0 (and a stamp for the head) or what blocks the PR: "
                                            "open, fresh on its files, merge-check, CI green, reviewed, public "
                                            "stamp, body")
    mr.add_argument("pr", help="the PR's number (or its URL or branch, as gh pr view takes it)")
    mr.add_argument("--repo-dir", metavar="D", help="a checkout of the PR's repo (default: the current folder)")
    mr.add_argument("--slug", metavar="OWNER/NAME", help="the GitHub repo (default: the remote's)")
    mr.add_argument("--remote", help="the remote the base and the head are fetched from (default: origin)")
    mr.add_argument("--no-fetch", action="store_true", help="the base and the head as last fetched")
    mr.add_argument("--with", dest="with_", action="append", metavar="PR",
                    help="another PR merged with it, in this order (repeatable, or comma-separated)")
    mr.add_argument("--test", action="store_true", help="--with: run the tests brain impact chooses for the set in a "
                                                        "scratch worktree of the integrated commit")
    mr.add_argument("--python", metavar="P", help="--test: the Python that runs pytest (default: this one)")
    mr.add_argument("--json", action="store_true")
