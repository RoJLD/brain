"""Load and save the engine's own state files safely (wi-brain-state-safe-io; spec-brain-data-compat N4, class
truth-local).

A truth-local file lives on one machine, with no git behind it: ``$BRAIN_HOME/schedules/installed.json``,
``alerts/state.json``, ``vault/state.json``, ``usage/sessions.json``... Losing one loses a record nothing else keeps
(the tasks this machine installed, the alerts already sent, the drill's proof, the usage of deleted transcripts).
:func:`load` and :func:`save` give every such file the same policy:

- **missing**: an empty record, writable;
- **unreadable or the wrong shape** (not JSON, not an object, or a shape its owner's ``check`` refuses): the file is
  *set aside* beside itself (``<name>.unreadable-<UTC stamp>``), never replaced by ``{}`` and saved over; the record
  starts afresh and a line on stderr names the copy;
- **a ``v`` above the one this engine knows**: written by a newer brain. Its data is read as it is (a tolerant
  reader), but the file is *read-only* for this engine: :func:`save` raises :class:`StateError` ("brain update"),
  and the commands that would write it refuse up front;
- a ``v`` that is not an integer: read-only too, since this engine cannot tell what wrote it;
- **an OSError other than a missing file** (a lock, a permission): read-only, and nothing is moved;
- a read-only command (``aside=False``: status, the cockpit, a plan) never moves a file: it reads a bad one as empty
  and read-only, and the next write sets it aside. A file replaced by a writer between the read and the move is
  read again, never set aside;
- **the write**: a backup of the file on disk first (``<name>.bak``, beside it: the same folder, so the same store
  and the same data class; a store under ``$BRAIN_HOME/secrets`` is never copied), then a temporary file, flushed
  and synced, moved over the file with ``os.replace``. The file on disk is checked again just before: a newer brain
  that wrote it since the load still wins.

The version locator is the top-level key ``v``, an integer. It never reaches the caller's data: :attr:`State.data`
is the record without it, and :func:`save` writes it back. A file without ``v`` is read as version 1. A record keyed
by names (installed schedules, alert projects) may keep its version 1 unwritten (``write_v=False``), so that an
engine from before this helper, which reads every key as a name, keeps reading it; its first breaking change writes
``v: 2``, which this engine then refuses to overwrite.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import paths

VKEY = "v"
BACKUP = ".bak"
ASIDE = ".unreadable-"


class StateError(RuntimeError):
    """A state file this engine must not write: written by a newer brain, or not readable here."""


@dataclass
class State:
    path: Path
    known: int
    data: dict = field(default_factory=dict)
    status: str = "missing"        # ok, missing, aside (set aside, started afresh), newer, unreadable
    v: object = None               # the version read (None without one)
    aside: Path | None = None
    why: str = ""

    @property
    def writable(self) -> bool:
        return self.status in ("ok", "missing", "aside")

    def refusal(self) -> str:
        """Why this engine must not write the file ('' when it may)."""
        if self.status == "newer":
            return (f"{self.path} was written by a newer brain (v {self.v}, this engine knows v {self.known}): "
                    "brain update; nothing written")
        if self.status == "unreadable":
            return f"{self.path} cannot be read ({self.why}): nothing written"
        return ""


def _version(raw: dict) -> object:
    """The version locator: None without one (a ``v`` that holds an object is a record named v, not a version)."""
    v = raw.get(VKEY)
    return None if v is None or isinstance(v, dict) else v


def set_aside(path: Path, why: str, seen: bytes | None = None) -> Path | None:
    """Move an unreadable file beside itself, under a name no later load reads; the copy's path. With ``seen`` (the
    bytes judged unreadable), None when the file changed since: a writer replaced it, and its record is kept."""
    if seen is not None and path.read_bytes() != seen:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(f"{path.name}{ASIDE}{stamp}")
    n = 1
    while target.exists():
        n += 1
        target = path.with_name(f"{path.name}{ASIDE}{stamp}-{n}")
    os.replace(path, target)
    print(f"brain: {path} {why}: set aside as {target.name}, the record starts afresh", file=sys.stderr)
    return target


def load(path: Path, *, known: int = 1, check: Callable[[dict], str] | None = None, aside: bool = True) -> State:
    """The record in ``path`` under this module's policy. ``check`` returns why a parsed object is the wrong shape
    ('' when it is right); it sees the record without its ``v``. ``aside=False`` (a read-only command: status, the
    cockpit, a plan) reads without moving anything: a file that would be set aside reads as unreadable, so empty and
    read-only, and the next command that writes it sets it aside."""
    st = State(path=Path(path), known=known)
    try:
        blob = st.path.read_bytes()
    except FileNotFoundError:
        return st
    except OSError as exc:
        st.status, st.why = "unreadable", exc.__class__.__name__
        return st
    why = ""
    try:
        raw = json.loads(blob.decode("utf-8"))
    except ValueError as exc:   # UnicodeDecodeError included: a byte that is not UTF-8
        raw, why = None, f"is not JSON ({exc.__class__.__name__})"
    if not why and not isinstance(raw, dict):
        why = f"is not an object (a {type(raw).__name__})"
    if not why:
        st.v = _version(raw)
        data = {k: val for k, val in raw.items() if not (k == VKEY and not isinstance(val, dict))}
        if st.v is not None and (not isinstance(st.v, int) or isinstance(st.v, bool)):
            st.status, st.data, st.why = "newer", data, f"v {st.v!r} is not an integer"
            return st
        if st.v is not None and st.v > known:
            st.status, st.data = "newer", data
            return st
        why = (check(data) if check else "") or ""
        if not why:
            st.status, st.data = "ok", data
            return st
        why = f"is not the expected shape ({why})"
    if not aside:
        st.status, st.why = "unreadable", why
        return st
    try:
        st.aside = set_aside(st.path, why, blob)
    except OSError as exc:
        st.status, st.why = "unreadable", f"{why}; setting it aside failed: {exc.__class__.__name__}"
        return st
    if st.aside is None:   # replaced by a writer since it was read: read it again
        return load(path, known=known, check=check, aside=aside)
    st.status, st.why = "aside", why
    return st


def _secret(path: Path) -> bool:
    try:
        path.resolve().relative_to((paths.brain_home() / "secrets").resolve())
    except (ValueError, OSError):
        return False
    return True


def _on_disk_newer(path: Path, known: int) -> object:
    """The ``v`` of the file on disk when it is above ``known`` (or not an integer), else None."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    v = _version(raw)
    if v is None:
        return None
    return v if not isinstance(v, int) or isinstance(v, bool) or v > known else None


def backup(path: Path) -> Path | None:
    """A copy of ``path`` beside it (``<name>.bak``), written atomically; None when there is nothing to copy, the
    file is a secret, or the copy failed (a ``.bak`` locked by a scanner: said on stderr, the write goes on)."""
    if not path.is_file() or _secret(path):
        return None
    bak = path.with_name(path.name + BACKUP)
    tmp = path.with_name(f"{path.name}{BACKUP}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(path, tmp)
        os.replace(tmp, bak)
    except OSError as exc:
        print(f"brain: {path}: no backup ({exc.__class__.__name__}); written without one", file=sys.stderr)
        return None
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return bak


def write_atomic(path: Path, text: str) -> None:
    """``text`` into ``path`` through a temporary file beside it, synced, then moved over it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def save(state: State, data: dict | None = None, *, write_v: bool = True, **dump) -> None:
    """Write ``data`` (``state.data`` by default) back to ``state.path``: refused (:class:`StateError`) when the
    load found it read-only or a newer brain wrote it since; a backup, then an atomic write. ``write_v`` writes the
    ``v`` this engine knows; ``dump`` goes to ``json.dumps`` (``indent=1, sort_keys=True`` by default)."""
    why = state.refusal()
    if why:
        raise StateError(why)
    data = state.data if data is None else data
    newer = _on_disk_newer(state.path, state.known)
    if newer is not None:
        state.status, state.v = "newer", newer
        raise StateError(state.refusal())
    body = {VKEY: state.known, **{k: v for k, v in data.items() if k != VKEY}} if write_v else dict(data)
    opts = {"indent": 1, "sort_keys": True, "ensure_ascii": False}
    opts.update(dump)
    backup(state.path)
    write_atomic(state.path, json.dumps(body, **opts) + "\n")
    state.data, state.status = data, "ok"
    if write_v:
        state.v = state.known
