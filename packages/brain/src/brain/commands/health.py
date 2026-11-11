"""``brain health``: check the named stacks, else the watched ones (--all: every one); starts nothing; STALE: a Compose
stack's containers differ from its compose file; code-index (or --all): STALE when a repo's branch moved past its
indexed commit.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import codeindex, config, projects, sessionarchive, spool, stacks, vault
from ._common import root_of

ORDER = 340   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 440   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain health [STACK]... [--all]   check the named stacks, the watched ones, or every one; starts nothing; a
                                  Compose stack whose containers differ from its compose file is STALE, one outside
                                  this machine's profile and not up is OFF (not a failure); the name
                                  code-index (or --all) checks the code index: STALE when a repo's branch moved
                                  past its indexed commit, it was never indexed or GitNexus lost it; --project P:
                                  every stack of P, then P's code index; a bundle's name (sovereign) stands for its
                                  components in up, down and health; the name vault (or --all): every canary sealed
                                  within 26 h and opened by this machine's device key, two recipients at least
                                  (brain.vault), OFF without a vault block or without age and gpg; the name
                                  spool (or --all): the last brain spool push's age and what waits to be sent
                                  (brain.spool), a warning past 7 days, FAIL when a waiting file no longer
                                  matches its sha256, OFF when never pushed; the name session-archive (or
                                  --all): the age of the last session archive run that sealed something
                                  (brain.sessionarchive), a warning past 7 days or without gitleaks, OFF while
                                  config.json session_archive.enabled is not true
"""

# The machine's own checks, each named by its CHECK and run with --all: health(cfg, named=...) -> exit code.
MACHINE_CHECKS = (vault, spool, sessionarchive)


def cmd_health(args, root: Path | None, project: str | None) -> int:
    """``brain health``: the stacks asked for (no name: the watched ones, every one with --all, every one of the
    project with --project), then the code index when code-index is named, with --all, or with --project alone, and
    the vault's canaries when vault is named or with --all, the spool's last push when spool is named or with
    --all, the session archive's last run when session-archive is named or with --all."""
    names = [n for n in args.stacks if n not in (codeindex.CHECK, *(m.CHECK for m in MACHINE_CHECKS))]
    rc = stacks.main("health", names, args.all, root, project=project) if names or not args.stacks else 0
    for mod in MACHINE_CHECKS:
        if mod.CHECK in args.stacks or args.all:
            rc = max(rc, mod.health(config.load(root), named=mod.CHECK in args.stacks))
    if not (codeindex.CHECK in args.stacks or args.all or (project and not args.stacks)):
        return rc
    try:
        return max(rc, codeindex.health(root, named=codeindex.CHECK in args.stacks, project=project))
    except codeindex.CodeIndexError as exc:
        print(f"brain health: {exc}", file=sys.stderr)
        return 2


def register(sub, ctx) -> None:
    sp = sub.add_parser("health", help="check the named stacks, else the watched ones (--all: every one); starts "
                                       "nothing; STALE: a Compose stack's containers differ from its compose file; "
                                       "code-index (or --all): STALE when a repo's branch moved past its indexed commit")
    sp.add_argument("stacks", nargs="*", metavar="STACK")
    sp.add_argument("--all", action="store_true", help="every declared stack, then the code index")
    sp.add_argument("--hook", action="store_true", help="SessionStart hook: hook JSON on stdin, the watched "
                    "stacks that are down as context, silent when all is well")


def early(args) -> int:
    if args.hook:  # a hook: never fails, silent when all is well
        return stacks.hook_main(["SessionStart"])
    root = root_of(args)
    if args.project:  # stack and repo names are global: any project's registry
        projects.get(args.project, root)  # an unknown project stops here
    return cmd_health(args, root, args.project)
