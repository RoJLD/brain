"""The engine's migrations of its own formats (wi-brain-migrate): ``brain migrate --plan``
(the default, read-only) and ``--apply``.

A format the engine reads carries its version, ``v`` (docs/formats.md, « The rule »): an additive change keeps it, a
rename, a removal or a change of meaning bumps it and ships a migration. A migration is a chain of :class:`Step`, one
per version, each a pure function from the record (a dict, without its ``v``) to the record of the next version,
registered in :data:`STEPS` by ``(format, from v)`` with :func:`step`. The formats it covers are :data:`FORMATS`: the
brain's ``config.json`` (the ``brain config migrate`` of the boundary design: config.json is one of these formats) and
the truth-local files of ``$BRAIN_HOME`` that carry a ``v`` (brain.stateio). A log is never rewritten (its reader
upcasts a line), and a derived file is rebuilt, never migrated: neither is listed.

- **What is pending is the file's own** ``v``: a file at version N is pending when a step from N is registered, and
  it is carried along the chain as far as the steps go. A file whose ``v`` has no step is read in place by its
  reader (an additive change, or one its reader upcasts); one above the engine's is a newer brain's (« brain
  update »), never touched. Since the file says where it is, a step never runs twice: re-running applies nothing.
- **The plan** reads each file and writes nothing: its format, its ``v``, the steps from it, and why a file cannot
  be migrated here (not JSON, a newer brain's, a config.json with changes not committed).
- **The apply**, file by file (config.json first): the file read again and compared with the plan, every step run in
  memory, a backup taken (a ``$BRAIN_HOME`` file beside itself, ``<name>.<UTC stamp>.bak``, the same store and data
  class; a file of a git work tree under ``$BRAIN_HOME/backup/<project>-<key>/`` so that git status stays clean:
  brain.stateio.backup_home, the last 10 copies kept), then one atomic write (a temporary file moved over it, its
  key order, indent, line endings and BOM kept: brain.update.rewrite_json), and each step appended to the
  applied-steps log, ``$BRAIN_HOME/migrate/applied.jsonl``. The first failure stops the run: a step that raises,
  a backup that cannot be taken, a write that fails (a full disk) leave that file as it was, and no later file is
  touched. A run cut between two files (killed) leaves each file whole at its own version: the next run resumes
  from there.
- A repo's file (config.json) is migrated in its work tree and never committed here: its diff is the migration, to
  commit or review by PR. One with changes not committed is refused, so that the diff is the migration's alone.

The engine ships no real step yet (no format has broken since its ``v`` was written): the framework, its registry
and its log are what the first breaking change fills.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__, config, faults, paths, stateio

LOG_DIR = "migrate"            # $BRAIN_HOME/migrate (classes.ENGINE_STORES)
LOG_FILE = "applied.jsonl"     # one line per step applied: {v, at, engine, format, file, step, from, to, backup}
LOG_V = 1


@dataclass(frozen=True)
class Format:
    """A format ``brain migrate`` reads: its id, its file (``config.json``: the brain's, found as brain.config finds
    it; any other: relative to ``$BRAIN_HOME``), the store it lives in, the version this engine reads and writes
    (None: the schema's, ``config.schema.json``) and the module that owns it (the reader the test holds it to)."""
    id: str
    path: str
    store: str
    known_v: int | None
    owner: str

    @property
    def repo(self) -> bool:
        """Whether the file lives in the brain's repo (git holds its history) rather than in ``$BRAIN_HOME``."""
        return self.id == "config"

    def known(self) -> int:
        if self.known_v is not None:
            return self.known_v
        from . import schema
        return schema.known_v("config")

    def where(self) -> str:
        return self.path if self.repo else f"$BRAIN_HOME/{self.path}"

    def file(self, root: Path | None = None) -> Path | None:
        """The file of this format on this machine, None when there is none."""
        if self.repo:
            f = config.config_file(root)
        else:
            f = paths.brain_home() / self.path
        return f if f is not None and f.is_file() else None


# The formats brain migrate covers, in the order --apply takes them: the brain's config.json, then the truth-local
# files of $BRAIN_HOME that carry a v (docs/formats.md, « Machine-local state »). A session's own files (sessions/,
# budget/) live as long as their session; a derived file (formats/<project>.json, update.json) is rebuilt; a log is
# upcast on read: none of them is migrated. tests/test_migrate.py holds each entry to its owner's path and version.
FORMATS: tuple[Format, ...] = (
    Format("config", "config.json", "config", None, "brain.config"),
    Format("schedules", "schedules/installed.json", "schedules", 1, "brain.schedule.record_file"),
    Format("alerts", "alerts/state.json", "alerts", 1, "brain.alerts.state_dir"),
    Format("vault", "vault/state.json", "vault", 1, "brain.vault.state_file"),
    Format("vault-device", "vault/device.json", "vault", 1, "brain.vault.device_file"),
    Format("usage", "usage/sessions.json", "usage", 2, "brain.usage.ledger_file"),
    Format("cockpit", "tui.json", "cockpit", 1, "brain.cockpit.state_path"),
    Format("memory-sync", "memory-sync/state.json", "memory-sync", 1, "brain.memory.sync_dir"),
    Format("machine", "machine.json", "machine.json", 1, "brain.machine.machine_file"),
    Format("spool", "spool/spool.json", "spool", 1, "brain.spool.index_file"),
    Format("session-archive", "session-archive/index.json", "session-archive", 1, "brain.sessionarchive.index_file"),
)
BY_ID = {f.id: f for f in FORMATS}


@dataclass(frozen=True)
class Step:
    """One version of one format: ``fn`` takes the record at ``frm`` (a copy, without its ``v``) and returns the
    record at ``to`` (``frm + 1``), without its ``v`` either: the runner writes it."""
    format: str
    frm: int
    to: int
    fn: Callable[[dict], dict]
    about: str

    @property
    def id(self) -> str:
        return f"{self.format}-v{self.frm}-v{self.to}"

    def row(self) -> dict:
        return {"id": self.id, "from": self.frm, "to": self.to, "about": self.about}


STEPS: dict[tuple[str, int], Step] = {}   # (format, from v) -> its step; the engine ships none yet


def register(s: Step) -> Step:
    """Add ``s`` to :data:`STEPS`: a known format, one version up, the only step from its version."""
    if s.format not in BY_ID:
        raise ValueError(f"brain migrate: {s.format!r} is not a format of brain.migrate.FORMATS")
    if not isinstance(s.frm, int) or s.frm < 1 or s.to != s.frm + 1:
        raise ValueError(f"brain migrate: a step goes one version up from v1 or later, not v{s.frm} -> v{s.to}")
    if (s.format, s.frm) in STEPS:
        raise ValueError(f"brain migrate: {s.format} already has a step from v{s.frm}")
    STEPS[(s.format, s.frm)] = s
    return s


def step(fmt: str, frm: int, about: str):
    """A decorator: the function becomes the step of ``fmt`` from ``frm`` to ``frm + 1``."""
    def add(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        register(Step(fmt, frm, frm + 1, fn, about))
        return fn
    return add


def chain(fmt: Format, v: int) -> list[Step]:
    """The steps from ``v``, in order, as far as they are registered and never past the version this engine knows."""
    out: list[Step] = []
    known = fmt.known()
    while (fmt.id, v) in STEPS and STEPS[(fmt.id, v)].to <= known:
        out.append(STEPS[(fmt.id, v)])
        v = out[-1].to
    return out


# --- the plan ---

@dataclass
class Entry:
    format: str
    file: Path
    v: object = None               # the file's version (1 without one), None when it could not be read
    known: int = 1
    status: str = "current"        # current, pending, newer, unreadable
    steps: list[Step] = field(default_factory=list)
    why: str = ""                  # what keeps a pending file from being migrated here ('' when nothing does)

    def row(self) -> dict:
        return {"format": self.format, "file": str(self.file), "v": self.v, "known": self.known,
                "status": self.status, "steps": [s.row() for s in self.steps], "why": self.why}


def _version(raw: dict) -> object:
    """The ``v`` of a record, 1 without one (a ``v`` that holds an object is a record named v: brain.stateio)."""
    v = raw.get(stateio.VKEY)
    return 1 if v is None or isinstance(v, dict) else v


def _read(path: Path) -> tuple[dict | None, str]:
    """The record in ``path`` and '' , or None and why it cannot be read (a BOM is read, as brain.config does)."""
    try:
        blob = faults.on_read(path, path.read_bytes())
    except OSError as exc:
        return None, f"cannot be read ({exc.__class__.__name__})"
    try:
        raw = json.loads(blob.decode("utf-8-sig"))
    except ValueError as exc:
        return None, f"is not JSON ({exc.__class__.__name__})"
    if not isinstance(raw, dict):
        return None, f"is not an object (a {type(raw).__name__})"
    return raw, ""


def _uncommitted(path: Path) -> bool:
    """Whether git holds changes not committed to ``path`` (False outside a work tree, or without git)."""
    try:
        r = subprocess.run(["git", "-C", str(path.parent), "status", "--porcelain", "--", path.name],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


def entry(fmt: Format, path: Path) -> Entry:
    """What ``path`` holds for ``fmt``, and the steps it is pending (read-only)."""
    e = Entry(fmt.id, path, known=fmt.known())
    raw, why = _read(path)
    if raw is None:
        e.status, e.why, e.v = "unreadable", f"{why}: left as it is (its own command sets it aside)", None
        return e
    e.v = _version(raw)
    if not isinstance(e.v, int) or isinstance(e.v, bool):
        e.status, e.why = "newer", f"v {e.v!r} is not an integer: left as it is"
    elif e.v > e.known:
        e.status, e.why = "newer", (f"written by a newer brain (v {e.v}, this engine knows v {e.known}): "
                                    "brain update; left as it is")
    else:
        e.steps = chain(fmt, e.v)
        if e.steps:
            e.status = "pending"
            if fmt.repo and _uncommitted(path):
                e.why = (f"{path.name} has changes not committed: commit them first, so that the migration's diff "
                         "is its own")
    return e


def plan(root: Path | None = None) -> list[Entry]:
    """Every file of :data:`FORMATS` on this machine, in --apply's order (read-only)."""
    out = []
    for fmt in FORMATS:
        f = fmt.file(root)
        if f is not None:
            out.append(entry(fmt, f))
    return out


def pending(root: Path | None = None) -> list[Entry]:
    """The files with steps to apply (brain update's line)."""
    return [e for e in plan(root) if e.status == "pending"]


# --- the apply ---

def log_file() -> Path:
    return paths.brain_home() / LOG_DIR / LOG_FILE


class Failed(RuntimeError):
    """A file that could not be migrated: it was left as it was."""


def _backup(fmt: Format, path: Path) -> Path:
    """The copy taken before the write (brain.stateio.backup_home): a work tree's file under ``$BRAIN_HOME/backup``
    (brain.permissions.home_backup_dir), any other beside itself. :class:`Failed` when none could be taken."""
    folder = None
    if fmt.repo:
        from . import permissions
        folder = permissions.home_backup_dir(path)
    bak = stateio.backup_home(path, folder if folder is not None else path.parent)
    if bak is None:
        raise Failed("no backup could be taken: nothing written")
    return bak


def _migrated(e: Entry, raw: dict) -> dict:
    """``raw`` carried along ``e.steps`` in memory: the new record, its ``v`` first."""
    data = {k: val for k, val in raw.items() if not (k == stateio.VKEY and not isinstance(val, dict))}
    for s in e.steps:
        try:
            out = s.fn(copy.deepcopy(data))
        except Exception as exc:  # noqa: BLE001 - a step is code: any failure stops the run, the file untouched
            raise Failed(f"step {s.id} failed ({exc.__class__.__name__}: {exc}): nothing written") from None
        if not isinstance(out, dict):
            raise Failed(f"step {s.id} returned a {type(out).__name__}, not a record: nothing written")
        data = {k: val for k, val in out.items() if not (k == stateio.VKEY and not isinstance(val, dict))}
    new = {stateio.VKEY: e.steps[-1].to, **data}
    try:
        json.dumps(new)
    except (TypeError, ValueError) as exc:
        raise Failed(f"step {e.steps[-1].id} made a record JSON cannot hold ({exc}): nothing written") from None
    return new


def apply_one(e: Entry) -> tuple[Path, list[dict]]:
    """Migrate one pending file: its backup and the log's lines. :class:`Failed`, the file as it was, otherwise."""
    from .update import rewrite_json

    fmt = BY_ID[e.format]
    if e.why:
        raise Failed(e.why)
    raw, why = _read(e.file)
    if raw is None or _version(raw) != e.v:
        raise Failed(f"changed since the plan ({why or 'its v moved'}): run brain migrate again")
    new = _migrated(e, raw)
    bak = _backup(fmt, e.file)

    def change(data: dict) -> None:
        if data != raw:   # written by another command since it was read: never over it
            raise ValueError("changed while it was migrated: run brain migrate again")
        data.clear()
        data.update(new)
    try:
        rewrite_json(e.file, change)
    except ValueError as exc:
        raise Failed(f"{exc}; nothing written") from None
    except OSError as exc:   # a full disk, a lock: the temporary file is gone, the file is as it was
        raise Failed(f"the write failed ({exc.__class__.__name__}: {exc}): the file is as it was") from None
    at = faults.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [{"v": LOG_V, "at": at, "engine": __version__, "format": e.format, "file": str(e.file), "step": s.id,
             "from": s.frm, "to": s.to, "backup": str(bak)} for s in e.steps]
    return bak, rows


def _log(rows: list[dict]) -> None:
    from .timing import append_text
    append_text(log_file(), "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))


def applied() -> list[dict]:
    """The log's lines, oldest first (a line that is not a JSON object is skipped)."""
    try:
        text = log_file().read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def apply(entries: list[Entry]) -> tuple[list[dict], dict | None]:
    """Each pending file migrated in order, stopping at the first failure: the log's lines written, and the failure
    ({format, file, why}) or None."""
    done: list[dict] = []
    for e in entries:
        if e.status != "pending":
            continue
        try:
            _bak, rows = apply_one(e)
        except Failed as exc:
            return done, {"format": e.format, "file": str(e.file), "why": str(exc)}
        try:
            _log(rows)
        except OSError as exc:
            done += rows
            return done, {"format": e.format, "file": str(e.file),
                          "why": f"migrated, but the log {log_file()} could not be written ({exc.__class__.__name__})"}
        done += rows
    return done, None


# --- the command ---

def _plan_lines(entries: list[Entry]) -> list[str]:
    todo = [e for e in entries if e.status == "pending"]
    steps = sum(len(e.steps) for e in todo)
    out = []
    for e in entries:
        fmt = BY_ID[e.format]
        if e.status == "pending":
            for s in e.steps:
                out.append(f"  pending  {fmt.where()} ({e.format}) v{s.frm} -> v{s.to}  {s.id}: {s.about}")
            if e.why:
                out.append(f"  blocked  {fmt.where()}: {e.why}")
        elif e.status != "current":
            out.append(f"  {e.status:<8} {fmt.where()}: {e.why}")
    if not todo:
        head = f"brain migrate: nothing pending ({len(entries)} file(s) read, each at a version this engine reads)"
    else:
        head = (f"brain migrate: {steps} step(s) pending on {len(todo)} file(s); nothing written "
                "(brain migrate --apply runs them, a backup first)")
    return [head, *out]


def main(root: Path | None, *, do_apply: bool = False, as_json: bool = False, out=print) -> int:
    """brain migrate: the plan (read-only), or with ``do_apply`` its run. Exit 1 on a failure."""
    entries = plan(root)
    if not do_apply:
        if as_json:
            out(json.dumps({"engine": __version__, "log": str(log_file()), "files": [e.row() for e in entries],
                            "pending": sum(len(e.steps) for e in entries if e.status == "pending")},
                           ensure_ascii=False, indent=1, sort_keys=True))
        else:
            out("\n".join(_plan_lines(entries)))
        return 0
    done, failed = apply(entries)
    if as_json:
        out(json.dumps({"engine": __version__, "log": str(log_file()), "files": [e.row() for e in entries],
                        "applied": done, "failed": failed}, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        lines = [f"applied  {r['file']}: {r['step']} v{r['from']} -> v{r['to']} (backup {r['backup']})" for r in done]
        if failed:
            lines.append(f"failed   {failed['file']}: {failed['why']}; nothing further applied")
        elif not done:
            lines.append("brain migrate: nothing to apply (each file is at a version this engine reads)")
        else:
            lines.append(f"brain migrate: {len(done)} step(s) applied; the log is {log_file()}")
        out("\n".join(lines))
    if failed and as_json:   # the JSON on stdout holds it; a line on stderr for whoever reads only that
        print(f"brain migrate: {failed['file']}: {failed['why']}", file=sys.stderr)
    return 1 if failed else 0
