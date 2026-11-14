"""``brain memory undo KEY/NAME.md`` (brain.memory): an import put back, only while the note still holds what was
imported, from the backup the import took (named by its content's hash, never overwritten)."""

from __future__ import annotations

import sys
from pathlib import Path

from .memory import SyncError, _write, backup, blob_id, load_state, normalize, save_state, sync_dir
from .memorykeys import local_dir, local_notes


def _undo_of(note: str) -> tuple[dict, dict, Path, Path | None]:
    """(the state, the import's record, the note's file, its backup or None when the import created it) for
    ``brain memory undo``; SyncError says why there is nothing to undo."""
    if "/" not in note:
        raise SyncError(f"{note}: name a note as KEY/NAME.md (brain memory status lists them)")
    state = load_state(write=True)
    rec = (state.get("imports") or {}).get(note)
    if not rec:
        raise SyncError(f"no import of {note} recorded (brain memory status lists the notes)")
    key, name = note.split("/", 1)
    folder = local_dir(key)
    target = local_notes().get(note) or (folder / name if folder else None)
    if target is None:
        raise SyncError(f"{note}: its project folder is not on this machine")
    saved = sync_dir() / rec["backup"] if rec.get("backup") else None
    if saved is not None and not saved.is_file():
        raise SyncError(f"{note}: its backup {rec['backup']} is gone; nothing changed")
    return state, rec, target, saved


def undo(note: str, out=None) -> int:
    """``brain memory undo KEY/NAME.md``: put back the copy the last import of that note replaced, only while the note
    still holds what was imported (its hash is the import's 'after'). Otherwise nothing is overwritten: the backup is
    written beside it as ``<name>.undo-conflict``, to merge by hand. Exit 1 when it did not restore. The undo sticks:
    main's version is recorded as declined, so the next sync neither imports it again nor exports the restored copy
    over it; a later version of main's is decided as usual."""
    out = out or sys.stdout
    try:
        state, rec, target, saved = _undo_of(note)
    except SyncError as exc:
        print(f"brain: {exc}", file=out)
        return 1
    key, name = note.split("/", 1)
    now = blob_id(normalize(target.read_bytes())) if target.exists() else None
    if now != rec.get("after"):
        if saved is None:
            print(f"brain: {note} changed since the import and had no copy before it: nothing to restore", file=out)
            return 1
        side = target.with_name(target.name + ".undo-conflict")
        _write(side, saved.read_bytes())
        print(f"brain: {note} changed since the import: left as it is; the copy before the import is {side}, "
              "merge it by hand", file=out)
        return 1
    if saved is None:   # the import created the note: undoing it removes it (main's copy stays in git)
        backup(key, name, target.read_bytes())
        target.unlink()
    else:
        _write(target, saved.read_bytes())
    del state["imports"][note]
    entry = state.setdefault("notes", {}).setdefault(note, {})
    entry["declined"] = rec.get("after")   # main's version stays declined here: not imported again, not exported
    save_state(state)
    print(f"brain: {note} restored to its copy before the import of {rec.get('at', '?')}", file=out)
    return 0
