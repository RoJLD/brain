"""``brain memory``: memory shared across machines by a reviewed PR: status, sync, undo."""

from __future__ import annotations

from .. import memory

ORDER = 430   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 400   # its usage lines' place in brain --help's epilog
RUNS_VIA = {   # brain perf --usage: how a subcommand that may never run from the CLI is reached (brain.adoption)
    "memory status": "on demand: a dry-run plan against main (the memory hook shows only the last sync's alert)",
    "memory sync": "wired: the memory hook (memory.sh) syncs at session end, detached",
    "memory undo": "on demand: the owner puts back a note an import replaced",
}
USAGE = """\
  brain memory status [--offline]   what a memory sync would do, note by note (export, import, conflict, kept),
                                  against main fetched now (--offline: as last fetched); writes nothing
  brain memory sync [--export-only]   the sync the SessionEnd hook starts detached, now and in the foreground:
                                  import what only main changed, then the secret scan and the export of what only this
                                  machine changed, from a recognized key, to memory/<machine>/<date> and its PR (never
                                  main, never over someone else's push: then <date>-2); a note with a secret stays
                                  here alone; exit 1 when a note was held or the sync fails (brain.memory)
  brain memory undo KEY/NAME.md   put back the copy the last import of that note replaced, only while the note still
                                  holds what was imported; else it writes <name>.undo-conflict beside it and exits 1
"""
NO_PROJECT = {"memory"}   # its parsers that take no --project after them


def register(sub, ctx) -> None:
    me = sub.add_parser("memory", help="memory shared across machines by a reviewed PR: status, sync, undo").add_subparsers(
        dest="memory_cmd", required=True)
    ms = me.add_parser("status", help="what a sync would do, note by note; writes nothing")
    ms.add_argument("--offline", action="store_true", help="against main as last fetched (no network)")
    my = me.add_parser("sync", help="sync now in the foreground: import, secret scan, export to the machine's branch "
                                    "of the day and its PR")
    my.add_argument("--export-only", action="store_true", help="import nothing (main's newer notes stay listed)")
    mu = me.add_parser("undo", help="put back the copy an import replaced, only while the note holds what was "
                                    "imported")
    mu.add_argument("note", help="the note, KEY/NAME.md as brain memory status lists it")


def early(args) -> int:
    """Machine-wide: every project's memory folder, no repo root."""
    return memory.main_cli(args.memory_cmd, getattr(args, "offline", False), getattr(args, "export_only", False),
                           note=getattr(args, "note", ""))
