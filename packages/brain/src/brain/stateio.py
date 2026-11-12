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
  that wrote it since the load still wins;
- **integrity** (opt-in: config.json ``integrity.sidecars`` true, or ``$BRAIN_STATE_INTEGRITY=1``; off by default):
  :func:`save` writes a sidecar beside the file, ``<name>.sha256`` (its sha256, size and mtime), and :func:`load`
  checks it. A file whose size and mtime are the sidecar's but whose sha256 is not (bit rot) is set aside like an
  unreadable one, with its note; one whose size or mtime differ was written since by another writer (an older engine
  after a rollback): it loads, and the next save writes a fresh sidecar. A missing sidecar (every file before) loads
  as before; with integrity off, a save removes a sidecar left from before, so that none goes stale.

The version locator is the top-level key ``v``, an integer. It never reaches the caller's data: :attr:`State.data`
is the record without it, and :func:`save` writes it back. A file without ``v`` is read as version 1. A record keyed
by names (installed schedules, alert projects) may keep its version 1 unwritten (``write_v=False``), so that an
engine from before this helper, which reads every key as a name, keeps reading it; its first breaking change writes
``v: 2``, which this engine then refuses to overwrite.

Two other classes go through this module (wi-brain-state-safe-io-rest):

- **foreign** (a file another tool owns: Claude Code's ``settings.json``): :func:`read_foreign` refuses one that
  cannot be read, is not JSON or not an object (« fix it by hand first »: never set aside, never replaced), and
  :func:`write_foreign` refuses to write over a file that changed since it was read, backs it up beside itself, or
  into a folder of ``$BRAIN_HOME/backup`` the caller names (:func:`backup_home`: a git work tree's file, so that git
  status stays clean), then writes atomically;
- **log** (append-only lines): :func:`rotate_log` moves a log of an earlier month (or one past
  :data:`LOG_MAX_BYTES`) aside as ``<stem>-<YYYY-MM>[-n]<suffix>`` before a line is appended, and
  :func:`prune_months` drops the monthly files older than their class's retention (:data:`LOG_RETENTION`; None:
  kept, a record); :func:`log_files` gives a reader the log's files in order.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from . import paths, shutdown

VKEY = "v"
BACKUP = ".bak"
ASIDE = ".unreadable-"
SIDECAR = ".sha256"                       # <name>.sha256 beside a truth-local file, with integrity on
INTEGRITY_ENV = "BRAIN_STATE_INTEGRITY"   # 1/on or 0/off: wins over config.json integrity.sidecars
_INTEGRITY: dict[tuple, bool] = {}        # (config.json, its mtime and size) -> integrity.sidecars, per process
_CONFIG_AT: dict[tuple, Path | None] = {}  # the environment that finds config.json -> where it is, per process
# The months a log class keeps, this one counted (None: kept, a record nothing else holds). The engine's errors
# (ledger/errors.log and its monthly files), its self-timing (engine/*.jsonl), the ledgers of records
# (ledger/<name>-YYYY-MM.jsonl: actions, decisions, events, guard decisions, the queue); the governor's brainstorm
# starts (usage/starts.jsonl, read for 10 minutes: last month kept for a start just before the month turned), the
# quota readings (usage/quota.jsonl: the forecast calibrates on 28 days, the history by weeks), the notifications'
# audit (notify/YYYY-MM.jsonl, read two months back).
LOG_RETENTION: dict[str, int | None] = {"errors": 6, "timing": 3, "ledger": None, "starts": 2, "quota": 12,
                                        "notify": 6}
LOG_MAX_BYTES = 1_000_000
_MONTH_RE = re.compile(r"(?<!\d)\d{4}-\d{2}(?!\d)")


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

    @property
    def refused(self) -> bool:
        """Whether a writer will be refused, read without moving anything (``aside=False``): a newer brain's file, or
        one it cannot read at all (a lock, a permission); a file of the wrong shape is not, its writer sets it aside."""
        return self.status == "newer" or (self.status == "unreadable" and not self.why.startswith("is not"))

    def refusal(self) -> str:
        """Why this engine must not write the file ('' when it may)."""
        if self.status == "newer":
            return (f"{self.path} was written by a newer brain (v {self.v}, this engine knows v {self.known}): "
                    "brain update; nothing written")
        if self.status == "unreadable":
            return f"{self.path} cannot be read ({self.why}): nothing written"
        return ""


def integrity_on() -> bool:
    """Whether the sha256 sidecars are on: ``$BRAIN_STATE_INTEGRITY`` (1, on, true / 0, off, false), else config.json's
    ``integrity.sidecars`` (found without a repo acted on: ``$BRAIN_CONFIG``, else the personal brain's), else off. Read
    once per process while config.json keeps its time and size: a hook pays one stat."""
    env = os.environ.get(INTEGRITY_ENV, "").strip().lower()
    if env in ("1", "on", "true", "yes"):
        return True
    if env in ("0", "off", "false", "no"):
        return False
    f = _config_file()
    try:
        st = f.stat() if f else None
    except OSError:
        st = None
    if st is None:
        return False
    key = (str(f), st.st_mtime_ns, st.st_size)
    if key not in _INTEGRITY:
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = None
        block = data.get("integrity") if isinstance(data, dict) else None
        _INTEGRITY[key] = isinstance(block, dict) and block.get("sidecars") is True
    return _INTEGRITY[key]


def _config_file() -> Path | None:
    """config.json as found without a repo acted on: ``$BRAIN_CONFIG``, else the first of brain.paths.bases() that
    holds one (the personal brain's, through ``<BRAIN_HOME>/personal.json``). A place found is kept for the process
    (a hook saves often: then one stat per call); none found is looked for again at the next call."""
    env = os.environ.get("BRAIN_CONFIG")
    if env:
        return Path(env).expanduser()
    key = tuple(os.environ.get(k, "") for k in ("CLAUDE_BRAIN_DIR", "BRAIN_PERSONAL", "BRAIN_HOME"))
    if _CONFIG_AT.get(key) is None:
        _CONFIG_AT[key] = next((b / "config.json" for b in paths.bases() if (b / "config.json").is_file()), None)
    return _CONFIG_AT[key]


def sidecar(path: Path) -> Path:
    return Path(path).with_name(Path(path).name + SIDECAR)


def _read(path: Path) -> tuple[bytes, os.stat_result]:
    """A file's bytes and its stat through one handle: the two describe the same file even when a writer replaces it
    meanwhile."""
    with open(path, "rb") as fh:
        return fh.read(), os.fstat(fh.fileno())


def _check_sidecar(path: Path, blob: bytes, st: os.stat_result) -> str:
    """Why ``blob`` (the file read, ``st`` its stat) fails its sidecar: '' when it matches, there is none, it cannot be
    read, or the file was written since by another writer (its size or time differ from the sidecar's: not bit
    rot)."""
    try:
        side = json.loads(sidecar(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(side, dict) or not isinstance(side.get("sha256"), str):
        return ""
    if side.get("size") != st.st_size or side.get("mtime_ns") != st.st_mtime_ns or len(blob) != st.st_size:
        return ""
    return "" if hashlib.sha256(blob).hexdigest() == side["sha256"] else \
        "is not what its sha256 sidecar holds (its size and time unchanged: bit rot or a write outside the engine)"


def _drop_sidecar(path: Path) -> None:
    """Before a write: the old sidecar goes, so that a write cut short (a killed hook) leaves none rather than a stale
    one (a missing sidecar loads)."""
    try:
        sidecar(path).unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"brain: {sidecar(path)}: not removed ({exc.__class__.__name__})", file=sys.stderr)


def _write_sidecar(path: Path) -> None:
    """The sidecar of the file just written (integrity on; never for a secret's file), its bytes and stat read
    through one handle. Never raises: a sidecar that cannot be written leaves the file as it is (a missing sidecar
    loads)."""
    if _secret(path):
        return
    side = sidecar(path)
    try:
        blob, st = _read(path)
        write_atomic(side, json.dumps({"v": 1, "sha256": hashlib.sha256(blob).hexdigest(), "size": st.st_size,
                                       "mtime_ns": st.st_mtime_ns}) + "\n")
    except OSError as exc:
        print(f"brain: {side}: not written ({exc.__class__.__name__})", file=sys.stderr)


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
    side = sidecar(path)
    if side.exists():   # the sidecar goes with the copy it describes: the evidence of a mismatch, never stale here
        try:
            os.replace(side, sidecar(target))
        except OSError:
            pass
    print(f"brain: {path} {why}: set aside as {target.name}, the record starts afresh", file=sys.stderr)
    return target


def load(path: Path, *, known: int = 1, check: Callable[[dict], str] | None = None, aside: bool = True) -> State:
    """The record in ``path`` under this module's policy. ``check`` returns why a parsed object is the wrong shape
    ('' when it is right); it sees the record without its ``v``. ``aside=False`` (a read-only command: status, the
    cockpit, a plan) reads without moving anything: a file that would be set aside reads as unreadable, so empty and
    read-only, and the next command that writes it sets it aside."""
    st = State(path=Path(path), known=known)
    on = integrity_on()
    try:
        blob, stat = _read(st.path) if on else (st.path.read_bytes(), None)
    except FileNotFoundError:
        return st
    except OSError as exc:
        st.status, st.why = "unreadable", exc.__class__.__name__
        return st
    why = _check_sidecar(st.path, blob, stat) if on else ""
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
    """``text`` into ``path`` through a temporary file beside it, synced, then moved over it. A symbolic link is
    written through (the file it points to, a temporary file beside that one): the link stays a link."""
    path = Path(path)
    if path.is_symlink():
        path = Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with shutdown.critical():   # a signal waits for the file to be replaced (brain.shutdown)
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
    on = integrity_on()
    if on or sidecar(state.path).exists():   # off: a sidecar left from before goes, so none goes stale
        _drop_sidecar(state.path)
    write_atomic(state.path, json.dumps(body, **opts) + "\n")
    if on:
        _write_sidecar(state.path)
    state.data, state.status = data, "ok"
    if write_v:
        state.v = state.known


# --- foreign files: another tool's, edited in their own keys only ---

def read_foreign(path: Path) -> tuple[dict, bytes | None]:
    """A foreign JSON object (a UTF-8 BOM allowed) and the bytes it was read from: ``({}, None)`` when it is missing.
    :class:`StateError` when it cannot be read (a lock, a permission), is not JSON or is not an object: the owner
    fixes it by hand; it is never set aside nor replaced."""
    path = Path(path)
    try:
        blob = path.read_bytes()
    except FileNotFoundError:
        return {}, None
    except OSError as exc:
        raise StateError(f"{path}: cannot be read ({exc.__class__.__name__}): fix it by hand first; nothing written") \
            from None
    try:
        data = json.loads(blob.decode("utf-8-sig"))
    except ValueError as exc:
        raise StateError(f"{path}: not readable JSON ({exc}): fix it by hand first; nothing written") from None
    if not isinstance(data, dict):
        raise StateError(f"{path}: not a JSON object: fix it by hand first; nothing written")
    return data, blob


HOME_BACKUPS = 10   # the copies :func:`backup_home` keeps per file


def backup_home(path: Path, folder: Path, keep: int = HOME_BACKUPS) -> Path | None:
    """A copy of ``path`` into ``folder`` (``<name>.<UTC stamp>.bak``, a store of ``$BRAIN_HOME/backup``) unless the
    newest copy there holds the same bytes (that one is returned); then the copies past ``keep`` go, the oldest
    first. None when there is nothing to copy, the file is a secret, or the copy failed (said on stderr)."""
    path, folder = Path(path), Path(folder)
    if not path.is_file() or _secret(path):
        return None
    try:
        blob = path.read_bytes()
        folder.mkdir(parents=True, exist_ok=True)
        olds = sorted(p for p in folder.iterdir() if _home_copy_of(p.name, path.name))
        if olds and olds[-1].read_bytes() == blob:
            return olds[-1]
        t = datetime.now(timezone.utc)
        dst = folder / f"{path.name}.{t:%Y%m%dT%H%M%S%fZ}{BACKUP}"
        while dst.exists():   # a coarse clock (about 16 ms on Windows): never over another copy
            t += timedelta(microseconds=1)
            dst = folder / f"{path.name}.{t:%Y%m%dT%H%M%S%fZ}{BACKUP}"
        tmp = dst.with_name(f"{dst.name}.{os.getpid()}.tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, dst)
    except OSError as exc:
        print(f"brain: {path}: no backup in {folder} ({exc.__class__.__name__}); written without one", file=sys.stderr)
        return None
    for old in (olds + [dst])[:-max(keep, 1)]:
        try:
            old.unlink()
        except OSError:
            pass
    return dst


def _home_copy_of(name: str, of: str) -> bool:
    """Whether ``name`` is a copy :func:`backup_home` made of a file named ``of``."""
    stamp = name[len(of) + 1:-len(BACKUP)] if name.startswith(of + ".") and name.endswith(BACKUP) else ""
    return bool(re.fullmatch(r"\d{8}T\d{12}Z", stamp))


def write_foreign(path: Path, text: str, seen: bytes | None, *, keep_backup: bool = True,
                  backup_dir: Path | None = None) -> Path | None:
    """``text`` over a foreign file read as ``seen`` (its bytes then, None when it was missing): refused
    (:class:`StateError`) when the file changed since, since its owner wrote it meanwhile; a backup first, into
    ``backup_dir`` when given (:func:`backup_home`), else beside it unless ``keep_backup`` is False; then the atomic
    write. The backup's path, None without one."""
    path = Path(path)
    try:
        now = path.read_bytes()
    except FileNotFoundError:
        now = None
    except OSError as exc:
        raise StateError(f"{path}: cannot be read ({exc.__class__.__name__}): nothing written") from None
    if now != seen:
        raise StateError(f"{path}: changed while it was being edited (its owner wrote it): run the command again; "
                         "nothing written")
    bak = backup_home(path, backup_dir) if backup_dir is not None else backup(path) if keep_backup else None
    write_atomic(path, text)
    return bak


# --- the log class: monthly files, a retention per class ---

def month_of(name: str) -> str:
    """The ``YYYY-MM`` a log file's name carries ('' without one): its last one."""
    found = _MONTH_RE.findall(name)
    return found[-1] if found else ""


def oldest_kept(now: datetime, keep: int) -> str:
    """The oldest month a retention of ``keep`` months keeps, this one counted."""
    y, m = now.year, now.month - (max(keep, 1) - 1)
    while m < 1:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def prune_months(files: Iterable[Path], keep: int | None, now: datetime | None = None) -> list[Path]:
    """Remove the monthly log files older than ``keep`` months (this one counted; None keeps them all, a file whose
    name has no month is kept); the removed."""
    if keep is None:
        return []
    oldest, gone = oldest_kept(now or datetime.now(timezone.utc), keep), []
    for f in files:
        month = month_of(f.name)
        if month and month < oldest:
            try:
                f.unlink()
                gone.append(f)
            except OSError:
                pass
    return gone


def rotate_log(path: Path, now: datetime | None = None, *, keep: int | None = LOG_RETENTION["errors"],
               max_bytes: int = LOG_MAX_BYTES) -> Path | None:
    """Before a line is appended to ``path`` (a log whose lines carry their own time): a file last written in an
    earlier month (UTC) moves aside as ``<stem>-<its month><suffix>``, one past ``max_bytes`` the same way under
    this month (``-<n>`` added when that name is taken); then the monthly files older than ``keep`` months go. The
    moved file's path, None when nothing moved. Never raises: a log never fails its writer.

    Hooks rotate concurrently and without a lock: the move never replaces a file (:func:`_move_new`), and when the
    name was taken meanwhile the file is looked at again (another hook may have rotated it and a fresh one started),
    so a rotated month is never written over."""
    path = Path(path)
    now = now or datetime.now(timezone.utc)
    this, n = f"{now:%Y-%m}", 1
    for _ in range(_ROTATE_TRIES):
        try:
            st = path.stat()
        except OSError:
            return None
        month = time.strftime("%Y-%m", time.gmtime(st.st_mtime))
        if month >= this and st.st_size <= max_bytes:
            return None
        month = min(month, this)

        def name(k: int) -> Path:
            return path.with_name(f"{path.stem}-{month}{'' if k == 1 else f'-{k}'}{path.suffix}")
        while name(n).exists():
            n += 1
        target = name(n)
        try:   # looked at again: another hook may have rotated it and started a fresh one since the stat
            again = path.stat()
        except OSError:
            return None
        if (again.st_mtime_ns, again.st_size) != (st.st_mtime_ns, st.st_size):
            continue
        try:
            _move_new(path, target)
        except FileExistsError:
            n += 1     # taken since it was looked at: the log is looked at again, the next name tried
            continue
        except OSError:
            return None
        prune_months(path.parent.glob(f"{path.stem}-*{path.suffix}"), keep, now)
        return target
    return None


_ROTATE_TRIES = 8


def log_files(path: Path) -> list[Path]:
    """A rotated log's files, oldest first: its monthly files (``<stem>-<YYYY-MM>[-n]<suffix>``, by month, then n),
    then the live file when it exists. What a reader of the log's history reads after :func:`rotate_log`."""
    path = Path(path)
    rx = re.compile(rf"^{re.escape(path.stem)}-(\d{{4}}-\d{{2}})(?:-(\d+))?{re.escape(path.suffix)}$")
    try:
        names = [p for p in path.parent.iterdir() if p.is_file()]
    except OSError:
        names = []
    found = sorted(((m.group(1), int(m.group(2) or 1)), p) for p in names if (m := rx.match(p.name)))
    return [p for _, p in found] + ([path] if path.is_file() else [])


def _move_new(src: Path, dst: Path) -> None:
    """Move ``src`` to ``dst``, which must not exist: FileExistsError when it does (``os.replace`` would overwrite
    it). Windows' rename refuses an existing name; elsewhere a hard link does, then the old name goes (a file
    system without hard links: a rename, the name checked just before)."""
    if os.name == "nt":
        os.rename(src, dst)
        return
    try:
        os.link(src, dst)
    except FileExistsError:
        raise
    except OSError:
        if os.path.lexists(dst):
            raise FileExistsError(dst) from None
        os.rename(src, dst)
        return
    os.unlink(src)
