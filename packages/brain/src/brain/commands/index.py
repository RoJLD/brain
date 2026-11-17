"""``brain index``: have the code index (GitNexus, else codebase-memory-mcp) (re)index the repos declared under
code_index: (no name and no flag: each repo's state; brain.codebackends).
"""

from __future__ import annotations

from .. import codeindex, projects
from ._common import root_of

ORDER = 370   # its place in brain --help's list of commands (brain.commands)
PHASE = "early"   # its handlers: early only, before any root is resolved (brain.commands)
USAGE_ORDER = 460   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain index [REPO]... [--all] [--stale] [--backend gitnexus|cbm]
                                  have GitNexus (re)index the repos declared under code_index: (a snapshot
                                  of each one's branch in GitNexus's own store, then /api/analyze with embeddings),
                                  recording the indexed commit in $BRAIN_HOME/code-index.json; --stale: only those
                                  not indexed at their branch head; no name and no flag: each repo's state;
                                  --project P: only P's repos; --backend cbm: codebase-memory-mcp instead, the
                                  default when no stack declares index: (each checkout indexed in place, its
                                  settings set off first, recorded in $BRAIN_HOME/code-index/cbm/record.json)
"""


def register(sub, ctx) -> None:
    ix = sub.add_parser("index", help="have the code index (re)index the repos declared under code_index: (no name and "
                                      "no flag: each repo's state)")
    ix.add_argument("repos", nargs="*", metavar="REPO", help="a repo's folder name (GitNexus's name for it)")
    ix.add_argument("--all", action="store_true", help="every declared repo, even one indexed at its branch head")
    ix.add_argument("--stale", action="store_true", help="only the repos not indexed at their branch head (of the "
                                                         "named ones, else of every one)")
    ix.add_argument("--backend", choices=("gitnexus", "cbm"), help="the code index to use (default: gitnexus when a "
                                                                    "stack declares index:, else cbm when installed)")


def early(args) -> int:
    """Stack and repo names are global: any project's registry."""
    root = root_of(args)
    if args.project:
        projects.get(args.project, root)  # an unknown project stops here
    return codeindex.main(args.repos, args.all, args.stale, root, project=args.project, backend=args.backend)
