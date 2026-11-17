"""``brain impact``: before merge, what a change relies on in the graph: touched symbols and callers (the code index),
CodeRefs, nodes, then the checklist (brain.impact).
"""

from __future__ import annotations

from ._common import _whole, root_of

ORDER = 390   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 480   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain impact [--diff [BASE|A..B]] [--repo-dir D] [--depth N] [--backend gitnexus|cbm] [--json | --markdown]
                                  before merge, what a change relies on: the symbols it touches and their callers
                                  (the code index: GitNexus, codebase-memory-mcp first on a worktree, each the
                                  other's fallback), their CodeRefs, the graph nodes relying on them (the project's
                                  overlays read too), then a checklist: features whose status may change, docs to
                                  update, ADRs and specs to re-read, tests to run, open items; without a code index,
                                  file level and said so; --markdown: the checklist as a PR body's section, its
                                  tasks ticked by hand (brain.impact)
"""


def register(sub, ctx) -> None:
    im = sub.add_parser("impact", help="before merge, what a change relies on in the graph: touched symbols and "
                                       "callers (the code index), CodeRefs, nodes, then the checklist (brain.impact)")
    im.add_argument("--diff", nargs="?", const="", default="", metavar="BASE|A..B",
                    help="from merge-base(HEAD, the default branch, or BASE) to the working tree, or the commits A..B")
    im.add_argument("--repo-dir", metavar="D", help="the repo changed (default: the current folder)")
    im.add_argument("--depth", type=_whole, metavar="N", help="caller levels followed in the code index (default 2)")
    im.add_argument("--backend", choices=("gitnexus", "cbm"),
                    help="the code index asked (default: gitnexus, codebase-memory-mcp first on a worktree, each the "
                         "other's fallback when installed)")
    out = im.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true", help="the chain and the checklist as JSON")
    out.add_argument("--markdown", action="store_true", help="the checklist as a Markdown section for a PR body "
                                                             "(close-item puts it there)")


def early(args) -> int:
    """Like audit --diff: the changed repo may hold no graph store."""
    root = root_of(args)
    from .. import impact
    return impact.main(args, root)
