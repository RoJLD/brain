"""``brain migrate``: the engine's migrations of its own formats (brain.migrate, wi-brain-migrate): ``--plan`` (the
default, read-only) lists the steps each file is pending, ``--apply`` runs them, a backup first, each step logged.
"""

from __future__ import annotations

import argparse

from .. import migrate
from ._common import root_of

ORDER = 151   # its place in brain --help's list of commands (brain.commands): after update
USAGE_ORDER = 151   # its usage lines' place in brain --help's epilog, after brain update's
NO_PROJECT = {"migrate"}   # the brain's config.json and this machine's files: no project's
USAGE = """\
  brain migrate [--plan | --apply] [--json]   the engine's migrations of its own formats (docs/formats.md
                 « Migrations »): --plan, the default, reads the brain's config.json and this machine's truth-local
                 files and lists the steps each one is pending (its format, from v to v), writing nothing; --apply
                 runs them file by file, a backup first, one atomic write per file, each step appended to
                 $BRAIN_HOME/migrate/applied.jsonl; a file's own v says what is pending, so a second run applies
                 nothing. Exit 1 on a failure: that file is left as it was and nothing further is applied
"""


def register(sub, ctx) -> None:
    about = ("the engine's migrations of its own formats: --plan (the default) lists the steps the brain's "
             "config.json and this machine's truth-local files are pending, writing nothing; --apply runs them, a "
             "backup of each file first, one atomic write per file, each step logged under $BRAIN_HOME/migrate")
    mg = sub.add_parser("migrate", help=about, description=about)
    how = mg.add_mutually_exclusive_group()
    how.add_argument("--plan", action="store_true", help="list the pending steps and write nothing (the default)")
    how.add_argument("--apply", action="store_true", help="run them: each file backed up, migrated in memory, "
                                                          "written atomically; the first failure stops the run, "
                                                          "that file left as it was")
    mg.add_argument("--root", default=argparse.SUPPRESS,
                    help="the brain whose config.json is migrated (same as brain --root)")
    mg.add_argument("--json", action="store_true", help="the plan's data, or the run's (stable keys)")


def early(args) -> int:
    """Machine-wide, with the brain's config.json: no graph store needed."""
    return migrate.main(root_of(args), do_apply=args.apply, as_json=args.json)
