"""The engine's migrations of its own formats (wi-brain-migrate): ``brain migrate --plan`` (the default, read-only)
and ``--apply``.

A format the engine reads carries its version, ``v`` (docs/formats.md, « The rule »): an additive change keeps it, a
rename, a removal or a change of meaning bumps it and ships a migration. A migration is a chain of steps, one per
version, each a pure function from the record (a dict, without its ``v``) to the record of the next version. The
formats and the steps are the registry's, :mod:`brain.migrations`, which the readers use too: brain.stateio and
brain.config run a file's pending steps in memory when they load it, so a writer never saves a file at a version its
data does not have. This module is the eager, backed-up, logged version of the same steps.

- **What is pending is the file's own** ``v``: a file at version N is pending when the chain from N reaches the
  version this engine reads (or one its reader reads in place); a file it does not reach is ``behind`` (a step
  missing: refused, exit 1 on --apply). One above the engine's is a newer brain's (« brain update »), never touched.
  Since the file says where it is, a step never runs twice: re-running applies nothing.
- **The plan** reads each file and writes nothing: its format, its ``v``, the steps from it, and why a file cannot
  be migrated here (not JSON, a newer brain's, behind, a config.json with changes not committed or whose git status
  cannot be read).
- **The apply**, file by file (config.json first): the file read again and compared with the plan, every step run in
  memory, a backup taken (a ``$BRAIN_HOME`` file beside itself, ``<name>.<UTC stamp>.bak``, the same store and data
  class; a file of a git work tree under ``$BRAIN_HOME/backup/<project>-<key>/`` so that git status stays clean:
  brain.stateio.backup_home, the last 10 copies kept), a ``started`` line in the applied-steps log
  (``$BRAIN_HOME/migrate/applied.jsonl``, naming the backup), then one atomic write (a temporary file moved over it,
  its key order, indent, line endings and BOM kept: brain.update.rewrite_json; a ``$BRAIN_HOME`` file's integrity
  sidecar rewritten with it, brain.stateio.write_state), then one ``done`` line per step. The first failure stops the
  run: a step that raises, a backup that cannot be taken, a write that fails (a full disk) leave that file as it was,
  and no later file is touched. A run cut between two files (killed) leaves each file whole at its own version: the
  next run resumes from there.
- A repo's file (config.json) is migrated in its work tree and never committed here: its diff is the migration, to
  commit once every machine of the brain runs an engine that reads its new ``v`` (a machine behind fails closed until
  it updates). One with changes not committed is refused, so that the diff is the migration's alone.
- **A dev engine** (one run from a source folder) never migrates the default home (``$BRAIN_HOME`` unset): it would
  leave files the installed release refuses to write. ``--dev-engine`` says it is meant.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, faults, migrations, paths, stateio
from .migrations import Format, Step

LOG_DIR = "migrate"            # $BRAIN_HOME/migrate (classes.ENGINE_STORES)
LOG_FILE = "applied.jsonl"     # {v, at, engine, state: started|done, format, file, step(s), from, to, backup}
LOG_V = 1
DEV_FLAG = "--dev-engine"


# --- the plan ---

@dataclass
class Entry:
    format: str
    file: Path
    v: object = None               # the file's version (1 without one), None when it could not be read
    known: int = 1
    status: str = "current"        # current, pending, behind, newer, unreadable
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
    """The record in ``path`` and '', or None and why it cannot be read (a BOM is read, as brain.config does)."""
    try:
        blob = faults.on_read(path, path.read_bytes())
    except OSError as exc:
        return None, f"cannot be read ({exc.__class__.__name__}): left as it is, read-only for its own command too"
    try:
        raw = json.loads(blob.decode("utf-8-sig"))
    except ValueError as exc:
        return None, f"is not JSON ({exc.__class__.__name__}): left as it is (its own command sets it aside)"
    if not isinstance(raw, dict):
        return None, f"is not an object (a {type(raw).__name__}): left as it is (its own command sets it aside)"
    return raw, ""


def uncommitted(path: Path) -> str:
    """Why a work tree's ``path`` may not be migrated now ('' when it may): changes not committed to it, or a git
    status that cannot be read (fail closed: git missing, a repo of another owner). Outside a work tree: ''. Read
    with ``--no-optional-locks``, so the plan never takes the index's lock."""
    from . import permissions
    if permissions.work_tree(path) is None:
        return ""
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(path.parent), "status", "--porcelain", "--",
                            path.name], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"git status failed ({exc.__class__.__name__}): {path.name} is not migrated without it"
    if r.returncode != 0:
        said = (r.stderr.strip().splitlines() or [f"exit {r.returncode}"])[0][:200]
        return f"git status failed ({said}): {path.name} is not migrated without it"
    if r.stdout.strip():
        return f"{path.name} has changes not committed: commit them first, so that the migration's diff is its own"
    return ""


def entry(fmt: Format, path: Path) -> Entry:
    """What ``path`` holds for ``fmt``, and the steps it is pending (read-only)."""
    e = Entry(fmt.id, path, known=fmt.known())
    raw, why = _read(path)
    if raw is None:
        e.status, e.why, e.v = "unreadable", why, None
        return e
    e.v = _version(raw)
    if not isinstance(e.v, int) or isinstance(e.v, bool):
        e.status, e.why = "newer", f"v {e.v!r} is not an integer: left as it is"
    elif e.v > e.known:
        e.status, e.why = "newer", (f"written by a newer brain (v {e.v}, this engine knows v {e.known}): "
                                    "brain update; left as it is")
    else:
        e.steps, ok = migrations.reach(fmt, e.v)
        if not ok:
            e.status = "behind"
            e.why = (f"v {e.v} has no migration to v {e.known} in this engine (a step missing): left as it is, "
                     "read-only for its own command")
        elif e.steps:
            e.status = "pending"
            if fmt.repo:
                e.why = uncommitted(path)
    return e


def plan(root: Path | None = None) -> list[Entry]:
    """Every file of :data:`brain.migrations.FORMATS` on this machine, in --apply's order (read-only)."""
    out = []
    for fmt in migrations.FORMATS:
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


def dev_refusal(env: dict | None = None) -> str:
    """Why --apply must not run here ('' when it may): an engine run from a source folder (a dev checkout, an
    editable install; not a release clone under ``~/.brain/engine``) on the default home (``$BRAIN_HOME`` unset)."""
    env = os.environ if env is None else env
    if env.get("BRAIN_HOME"):
        return ""
    from . import skew
    folder = skew.engine_of("brain", "brain").folder
    if not folder:
        return ""
    clones = Path.home() / ".brain" / "engine"
    try:
        Path(folder).resolve().relative_to(clones.resolve())
        return ""
    except ValueError:
        pass
    return (f"this engine runs from {folder}, not an installed release, and BRAIN_HOME is the default home: its "
            "migration would leave files the installed brain refuses to write. Set BRAIN_HOME to a home of its own, "
            f"or pass {DEV_FLAG} to migrate this one anyway")


def _backup(fmt: Format, path: Path) -> Path:
    """The copy taken before the write (brain.stateio.backup_home): a work tree's file under ``$BRAIN_HOME/backup``
    (brain.permissions.home_backup_dir), any other beside itself. :class:`Failed` when none could be taken."""
    folder = None
    if fmt.repo:
        from . import permissions
        folder = permissions.home_backup_dir(path)
    bak = stateio.backup_home(path, folder if folder is not None else path.parent, say=False)
    if bak is None:
        raise Failed("no backup could be taken: nothing written")
    return bak


def _migrated(e: Entry, raw: dict) -> dict:
    """``raw`` carried along ``e.steps`` in memory: the new record, its ``v`` first."""
    data = {k: val for k, val in raw.items() if not (k == stateio.VKEY and not isinstance(val, dict))}
    try:
        data = migrations.run(e.steps, data)
    except migrations.StepFailed as exc:
        raise Failed(f"{exc}: nothing written") from None
    new = {stateio.VKEY: e.steps[-1].to, **data}
    try:
        json.dumps(new)
    except (TypeError, ValueError) as exc:
        raise Failed(f"step {e.steps[-1].id} made a record JSON cannot hold ({exc}): nothing written") from None
    return new


def _row(e: Entry, state: str, bak: Path, **more) -> dict:
    return {"v": LOG_V, "at": faults.now().strftime("%Y-%m-%dT%H:%M:%SZ"), "engine": __version__, "state": state,
            "format": e.format, "file": str(e.file), "backup": str(bak), **more}


def apply_one(e: Entry) -> list[dict]:
    """Migrate one pending file: the log's ``done`` lines (its ``started`` line already written).
    :class:`Failed`, the file as it was, otherwise."""
    from .update import rewrite_json

    fmt = migrations.BY_ID[e.format]
    if e.why:
        raise Failed(e.why)
    raw, why = _read(e.file)
    if raw is None or _version(raw) != e.v:
        raise Failed(f"changed since the plan ({why or 'its v moved'}): run brain migrate again")
    new = _migrated(e, raw)
    bak = _backup(fmt, e.file)
    try:   # the backup's path on record before the write: a run cut after it still names its copy
        _log([_row(e, "started", bak, steps=[s.id for s in e.steps], **{"from": e.v, "to": e.steps[-1].to})])
    except OSError as exc:
        raise Failed(f"the log {log_file()} cannot be written ({exc.__class__.__name__}): nothing written") from None

    def change(data: dict) -> None:
        if data != raw:   # written by another command since it was read: never over it
            raise ValueError("changed while it was migrated: run brain migrate again")
        data.clear()
        data.update(new)
    try:
        rewrite_json(e.file, change, write=stateio.write_atomic if fmt.repo else stateio.write_state)
    except ValueError as exc:
        raise Failed(f"{exc}; nothing written") from None
    except OSError as exc:   # a full disk, a lock: the temporary file is gone, the file is as it was
        raise Failed(f"the write failed ({exc.__class__.__name__}: {exc}): the file is as it was") from None
    return [_row(e, "done", bak, step=s.id, **{"from": s.frm, "to": s.to}) for s in e.steps]


def _log(rows: list[dict]) -> None:
    from .timing import append_text
    append_text(log_file(), "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))


def log_rows() -> list[dict]:
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


def applied() -> list[dict]:
    """The steps applied, oldest first (the log's ``done`` lines)."""
    return [r for r in log_rows() if r.get("state", "done") == "done"]


def unfinished() -> list[dict]:
    """The ``started`` lines no ``done`` line followed for the same file and version: a run cut after its backup
    (the file either migrated or as it was: its own ``v`` says which; the line names the copy to restore)."""
    out: dict[tuple, dict] = {}
    for r in log_rows():
        if r.get("state") == "started":
            out[(r.get("file"), r.get("to"))] = r
        elif r.get("state", "done") == "done":
            out.pop((r.get("file"), r.get("to")), None)
    return list(out.values())


def apply(entries: list[Entry]) -> tuple[list[dict], dict | None]:
    """Each pending file migrated in order, stopping at the first failure (a file behind is one): the log's ``done``
    lines written, and the failure ({format, file, why}) or None."""
    done: list[dict] = []
    for e in entries:
        if e.status == "behind":
            return done, {"format": e.format, "file": str(e.file), "why": e.why}
        if e.status != "pending":
            continue
        try:
            rows = apply_one(e)
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

CONFIG_ORDER = ("commit the migrated config.json once every machine of this brain runs an engine that reads v {to} "
                "(its pin moved and installed): a machine behind fails closed until it updates")


def _plan_lines(entries: list[Entry]) -> list[str]:
    todo = [e for e in entries if e.status == "pending"]
    steps = sum(len(e.steps) for e in todo)
    out = []
    for e in entries:
        fmt = migrations.BY_ID[e.format]
        if e.status == "pending":
            for s in e.steps:
                out.append(f"  pending  {fmt.where()} ({e.format}) v{s.frm} -> v{s.to}  {s.id}: {s.about}")
            if fmt.repo:
                out.append(f"  then     {CONFIG_ORDER.format(to=e.steps[-1].to)}")
            if e.why:
                out.append(f"  blocked  {fmt.where()}: {e.why}")
        elif e.status != "current":
            out.append(f"  {e.status:<8} {fmt.where()}: {e.why}")
    for r in unfinished():
        out.append(f"  cut      {r.get('file')}: a run stopped after its backup ({r.get('backup')}), v{r.get('from')} "
                   f"-> v{r.get('to')}: its own v says whether it was written")
    if not todo:
        head = f"brain migrate: nothing pending ({len(entries)} file(s) read)"
    else:
        head = (f"brain migrate: {steps} step(s) pending on {len(todo)} file(s); nothing written "
                "(brain migrate --apply runs them, a backup first)")
    return [head, *out]


def main(root: Path | None, *, do_apply: bool = False, as_json: bool = False, dev: bool = False, out=print) -> int:
    """brain migrate: the plan (read-only), or with ``do_apply`` its run. Exit 1 on a failure."""
    entries = plan(root)
    if not do_apply:
        if as_json:
            out(json.dumps({"engine": __version__, "log": str(log_file()), "files": [e.row() for e in entries],
                            "pending": sum(len(e.steps) for e in entries if e.status == "pending"),
                            "unfinished": unfinished()}, ensure_ascii=False, indent=1, sort_keys=True))
        else:
            out("\n".join(_plan_lines(entries)))
        return 0
    refused = "" if dev else dev_refusal()
    if refused:
        print(f"brain migrate --apply: {refused}; nothing written", file=sys.stderr)
        return 2
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
        if any(r["format"] == "config" for r in done):
            to = max(r["to"] for r in done if r["format"] == "config")
            lines.append(f"then     {CONFIG_ORDER.format(to=to)}")
        out("\n".join(lines))
    if failed and as_json:   # the JSON on stdout holds it; a line on stderr for whoever reads only that
        print(f"brain migrate: {failed['file']}: {failed['why']}", file=sys.stderr)
    return 1 if failed else 0
