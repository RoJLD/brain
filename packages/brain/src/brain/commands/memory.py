"""``brain memory``: memory shared across machines by a reviewed PR: status, sync."""

from __future__ import annotations

from .. import memory

ORDER = 430   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 400   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain memory status [--offline]   what a memory sync would do, note by note (export, import, conflict, kept),
                                  against main fetched now (--offline: as last fetched); writes nothing
  brain memory sync [--export-only]   the sync the SessionEnd hook starts detached, now and in the foreground:
                                  import what only main changed, then the secret scan and the export of what only this
                                  machine changed to memory/<machine>/<date> and its PR (never main); exit 1 when the
                                  export is refused or the sync fails (brain.memory)
"""
NO_PROJECT = {"memory"}   # its parsers that take no --project after them


def register(sub, ctx) -> None:
    me = sub.add_parser("memory", help="memory shared across machines by a reviewed PR: status, sync").add_subparsers(
        dest="memory_cmd", required=True)
    ms = me.add_parser("status", help="what a sync would do, note by note; writes nothing")
    ms.add_argument("--offline", action="store_true", help="against main as last fetched (no network)")
    my = me.add_parser("sync", help="sync now in the foreground: import, secret scan, export to the machine's branch "
                                    "of the day and its PR")
    my.add_argument("--export-only", action="store_true", help="import nothing (main's newer notes stay listed)")


def early(args) -> int:
    """Machine-wide: every project's memory folder, no repo root."""
    return memory.main_cli(args.memory_cmd, getattr(args, "offline", False), getattr(args, "export_only", False))
