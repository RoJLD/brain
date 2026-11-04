"""``brain tidy``: the project's stale worktrees and merged branches (and origin's with --remote), listed, then removed
with --apply; never an unmerged branch or a dirty worktree.
"""

from __future__ import annotations

from pathlib import Path

from .. import tidy
from ._common import _scope

ORDER = 290   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 140   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain tidy [--project P | --all] [--remote] [--apply] [--json]   at zero token, the project's repos: the stale
                        worktrees (clean, detached or on a merged branch, their desktop-app session archived or gone,
                        else idle 24 h), the local branches merged into the default branch, and with --remote origin's
                        merged branches (git ls-remote, read only); listed, then removed with --apply (git worktree
                        remove after the untracked junctions they hold, git branch -d; never --force, -D, an unmerged
                        branch or a dirty worktree; a production checkout: those two only); --remote --apply deletes
                        the remote ones (git push origin --delete) only outside a Claude Code session, where it prints
                        the brain queue add that puts the exact command to {owner}; --json: the plan
"""


def cmd_tidy(args, root: Path) -> int:
    """``brain tidy``: the stale worktrees and merged branches of the project's repos (--all: every registered
    project's), listed, then removed with --apply (brain.tidy)."""
    return tidy.main(_scope(args, root), remote=args.remote, apply=args.apply, as_json=args.json)


def register(sub, ctx) -> None:
    who = ctx.who
    td = sub.add_parser("tidy", help="the project's stale worktrees and merged branches (and origin's with --remote), "
                                     "listed, then removed with --apply; never an unmerged branch or a dirty worktree")
    td.add_argument("--all", action="store_true", help="every project of the registry")
    td.add_argument("--remote", action="store_true", help="also origin's branches merged into the default branch "
                                                          f"(git ls-remote; deleting them is {who}'s)")
    td.add_argument("--apply", action="store_true", help="remove them: git worktree remove, git branch -d; with "
                                                         "--remote, git push origin --delete outside a Claude Code "
                                                         f"session only (in one: the brain queue add for {who})")
    td.add_argument("--json", action="store_true", help="the plan as JSON (no --apply)")


run = cmd_tidy
