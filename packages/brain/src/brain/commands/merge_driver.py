"""``brain merge-driver``: the git merge driver of the generated views, the logs and the graph's YAML: git runs it,
install defines it in a repo's git config.
"""

from __future__ import annotations

from pathlib import Path

ORDER = 490   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 150   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain merge-driver run BASE OURS THEIRS PATH [SIZE]   git's entry (merge.brain.driver ... %O %A %B %P %L) for the
                        paths .gitattributes gives merge=brain: a generated view keeps one side (the default branch's
                        when one side is its version) and is marked for brain refresh; journal.md and decisions.md
                        are unioned, new entries in date order; edges/*.yaml and a CHANGELOG's Unreleased section are
                        unioned; other graph YAML is merged by id; anything else, and any failure, as git merge-file
  brain merge-driver install [--repo R] [--launcher PATH] [--apply] [--json]   defines the driver in the repo's git
                        config (shared by its worktrees; the installer runs it), checks .gitattributes names it
  brain merge-driver status [--json] | replay [MERGE | OURS..THEIRS]... [--since DATE] [--repo R] [--json]
                        the views waiting for brain refresh here; past merges merged again by git merge-tree, as
                        text then with the driver (nothing checked out): what conflicted before and after
"""


def cmd_merge_driver(args) -> int:
    """brain merge-driver run|install|status|replay (brain.mergedriver)."""
    from .. import mergedriver
    if args.merge_cmd == "run":
        return mergedriver.run(args.base, args.ours, args.theirs, args.path,
                               int(args.size) if str(args.size).isdigit() else 7)
    repo = Path(getattr(args, "repo", None) or ".").resolve()
    if args.merge_cmd == "install":
        return mergedriver.install(repo, args.apply, args.launcher, args.json)
    if args.merge_cmd == "status":
        return mergedriver.status(repo, args.json)
    from .. import mergereplay
    return mergereplay.main_replay(repo, args.since, args.merges, args.json)


def register(sub, ctx) -> None:
    mg = sub.add_parser("merge-driver", help="the git merge driver of the generated views, the logs and the graph's "
                                             "YAML: git runs it, install defines it in a repo's git config").\
        add_subparsers(dest="merge_cmd", required=True)
    mgr = mg.add_parser("run", help="git's entry: merge.brain.driver = brain merge-driver run %%O %%A %%B %%P %%L")
    for name in ("base", "ours", "theirs", "path"):
        mgr.add_argument(name)
    mgr.add_argument("size", nargs="?", default="7", help="the conflict marker size (%%L)")
    mgi = mg.add_parser("install", help="define the driver in the repo's git config (its worktrees share it): the "
                                        "plan, or --apply; checks .gitattributes names it")
    mgi.add_argument("--repo", help="the repo (default: the one here)")
    mgi.add_argument("--launcher", help="the brain command git runs (default: brain on PATH, else this Python)")
    mgi.add_argument("--apply", action="store_true", help="write the git config (idempotent)")
    mgi.add_argument("--json", action="store_true")
    mgs = mg.add_parser("status", help="the views the driver kept from one side here, waiting for brain refresh")
    mgs.add_argument("--repo", help="the worktree (default: the one here)")
    mgs.add_argument("--json", action="store_true")
    mgp = mg.add_parser("replay", help="past merges merged again by git merge-tree, as text then with the driver "
                                       "(nothing checked out): the conflicted files before and after")
    mgp.add_argument("merges", nargs="*", metavar="MERGE", help="a merge commit, or OURS..THEIRS (two heads); none: "
                                                                "every merge reachable from HEAD (--since)")
    mgp.add_argument("--since", default="", help="the merges since this date (git log --since)")
    mgp.add_argument("--repo", help="the repo (default: the one here)")
    mgp.add_argument("--json", action="store_true")


def early(args) -> int:
    """Git's entry and a repo's git config: no graph store."""
    return cmd_merge_driver(args)
