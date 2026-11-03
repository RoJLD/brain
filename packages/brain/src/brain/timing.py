"""The execution-time ledger (spec 2026-10-30 governance §3.9, item wi-brain-exec-time-ledger): one event per run of a
command, a script or a step, written by ``brain timed -- <command>`` or by :class:`timed`, a context manager and a
decorator that projects import; ``brain perf`` (brain.perf) reads it back::

  from brain.timing import timed

  with timed("download f1v2", project="quant"):
      download()

  @timed("cycle L4", project="quant")      # @timed(): the task is module.function
  def layer_4(): ...

One event schema (``schemas/event.schema.json``), shared with a project's ops error events (wi-ops-error-catalog):
``{"v": 1, "kind": "exec", "at", "host", "project", "task", "version", "start", "end", "duration_s", "exit", ...}``;
an error event has the same envelope with ``kind: "error"``, ``code`` and ``severity``. ``at`` is when it happened (an
exec event's end) and picks the file: ``$BRAIN_HOME/ledger/<kind>-<yyyy-mm>.jsonl``, so ``exec-<yyyy-mm>.jsonl``.
Defaults: the project is ``$BRAIN_PROJECT``, else the registered project whose root holds the working folder (a
worktree's main checkout's), else the repo's folder name; the version is ``$BRAIN_VERSION``, else the short SHA of HEAD
of the working folder's repo; the host ``$BRAIN_HOST``, else the host name.

Several writers at once (sessions, scheduled tasks, threads): each event is one line, written by one ``os.write`` on a
descriptor opened with ``O_APPEND``, while holding an exclusive lock on ``<ledger>/exec.lock`` (``msvcrt.locking`` on
Windows, ``fcntl.flock`` elsewhere). The lock is what makes it safe: on Windows the C runtime emulates ``O_APPEND`` by a
seek to the end, then a write, and another process can get between the two, so two lines land on the same offset
(measured on Windows 11, 8 processes writing 300 events each: 1,851 and 1,798 lines of 2,400 without the lock, some
mixed; 2,400 with it). Only the write is held: the file is opened before and closed after, since closing a written
file can take milliseconds (an antivirus scan). A writer that cannot get the lock within LOCK_TIMEOUT writes anyway and
says so in ``ledger/errors.log``: an event is never dropped and the timed work never waits long. A last line left without its newline (a writer killed
mid-write) is closed before the next one; readers skip a line that is not JSON.

Standard library only. Writing never fails the timed work: an error goes to ``ledger/errors.log``. ``BRAIN_TIMED=0``
turns the writing off.
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import random
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import paths, schema, secretscan

LOCK_NAME = "exec.lock"
LOCK_TIMEOUT = 5.0
LOCK_POLL = (0.0005, 0.005)  # first and longest sleep between two tries, in seconds
INTERRUPT_GRACE = 10.0
TASK_MAX, COMMAND_MAX, ERROR_MAX = 200, 500, 200
FIELDS = {"details", "log", "command", "error"}  # what a caller may add to an exec event
_BINARY = getattr(os, "O_BINARY", 0)
_thread_lock = threading.Lock()

# Side effects, replaced by fakes in the tests.
_clock = time.monotonic
_sleep = time.sleep

if os.name == "nt":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def locked(ledger: Path, timeout: float | None = None):
    """Hold the ledger's write lock; yields False when it could not be had within ``timeout`` (LOCK_TIMEOUT)."""
    timeout = LOCK_TIMEOUT if timeout is None else timeout
    with _thread_lock:
        fd = os.open(ledger / LOCK_NAME, os.O_RDWR | os.O_CREAT | _BINARY, 0o644)
        try:
            # polled (Windows has no blocking lock with a timeout): short sleeps with jitter, so that a writer is not
            # starved by others that come and go while it sleeps; a hold lasts about a millisecond
            deadline, wait = _clock() + timeout, LOCK_POLL[0]
            got = _try_lock(fd)
            while not got and _clock() < deadline:
                _sleep(wait * random.uniform(0.5, 1.5))
                wait = min(wait * 2, LOCK_POLL[1])
                got = _try_lock(fd)
            try:
                yield got
            finally:
                if got:
                    _unlock(fd)
        finally:
            os.close(fd)


def iso(dt: datetime) -> str:
    """UTC with milliseconds: 2026-11-02T10:00:00.123Z."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def fmt_duration(s: float) -> str:
    """4.2 s, 42 s, 3 min 05 s, 1 h 02 min."""
    if s < 10:
        return f"{s:.1f} s"
    if s < 59.5:
        return f"{s:.0f} s"
    if s < 3570:
        m, sec = divmod(round(s), 60)
        return f"{m} min {sec:02d} s"
    h, rest = divmod(round(s / 60), 60)
    return f"{h} h {rest:02d} min"


def _clean(text: str, limit: int) -> str:
    """One line, lines that match a secret pattern dropped, cut at ``limit``."""
    text = " ".join(secretscan.clean_text(str(text))[0].split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _log_error(what: str, exc: BaseException) -> None:
    from .capture import _log_error as log  # capture's errors.log: rotated, secrets dropped
    log(what, exc)


# The defaults: host, project, version.

def host() -> str:
    return os.environ.get("BRAIN_HOST") or socket.gethostname() or "unknown"


def _repo_top(d: Path) -> Path | None:
    for p in (d, *d.parents):
        if (p / ".git").exists():
            return p
    return None


@functools.lru_cache(maxsize=32)
def _project_of(cwd: str) -> str:
    from .midsession import _main_checkout

    here = Path(cwd).resolve()
    top = _repo_top(here)
    main = _main_checkout(top) if top else None
    try:
        from . import projects

        best = None
        for p in projects.load(main or here).values():
            root = p.root.resolve()
            for cand in (here, main):
                if cand and (cand == root or root in cand.parents) and (not best or len(root.parts) > best[1]):
                    best = (p.name, len(root.parts))
        if best:
            return best[0]
    except Exception:  # noqa: BLE001 - no registry, no PyYAML: the folder's name
        pass
    return (main or top or here).name or "unknown"


def project_for(cwd: str | Path | None = None) -> str:
    """$BRAIN_PROJECT, else the registered project whose root holds ``cwd`` (or its main checkout, for a worktree),
    else the name of the repo's main checkout, else the folder's name."""
    return os.environ.get("BRAIN_PROJECT") or _project_of(str(cwd or os.getcwd()))


@functools.lru_cache(maxsize=32)
def _head(cwd: str) -> str:
    from .actions import git
    return git(cwd, "rev-parse", "--short=10", "HEAD", timeout=3)


def version_for(cwd: str | Path | None = None) -> str:
    """$BRAIN_VERSION, else the short SHA of HEAD of the repo ``cwd`` is in ('' outside a repo)."""
    return os.environ.get("BRAIN_VERSION") or _head(str(cwd or os.getcwd()))


# Events.

def make_event(task: str, start: datetime, end: datetime, duration_s: float, exit: int | None, *,
               project: str | None = None, version: str | None = None, cwd: str | Path | None = None,
               **fields) -> dict:
    """An exec event; empty fields are left out. ``fields``: details, log, command, error (FIELDS)."""
    unknown = set(fields) - FIELDS
    if unknown:
        raise TypeError(f"unknown event field(s): {', '.join(sorted(unknown))} (allowed: {', '.join(sorted(FIELDS))})")
    ev = {"v": 1, "kind": "exec", "at": iso(end), "host": host(), "project": project or project_for(cwd),
          "task": _clean(task, TASK_MAX) or "unnamed", "version": version or version_for(cwd), "start": iso(start),
          "end": iso(end), "duration_s": round(max(duration_s, 0.0), 3), "exit": exit, "pid": os.getpid()}
    for k, v in fields.items():
        ev[k] = _clean(v, COMMAND_MAX if k == "command" else ERROR_MAX) if k in ("command", "error") and v else v
    return {k: v for k, v in ev.items() if k == "exit" or v not in (None, "", {})}


def write_event(event: dict, ledger: str | Path | None = None) -> Path:
    """Append ``event`` to ``<ledger>/<kind>-<yyyy-mm>.jsonl`` (ledger: $BRAIN_HOME/ledger) under the lock; the
    file. Raises ValueError when the event does not follow the schema."""
    errors, _ = schema.check("event", event)
    if errors:
        raise ValueError(f"invalid event: {'; '.join(errors[:3])}")
    d = Path(ledger) if ledger else paths.ledger_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{event['kind']}-{event['at'][:7]}.jsonl"
    data = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(f, os.O_RDWR | os.O_APPEND | os.O_CREAT | _BINARY, 0o644)
    try:
        with locked(d) as got:  # only the write is held: closing a written file can take ms (an antivirus scan)
            size = os.fstat(fd).st_size
            if size:
                os.lseek(fd, size - 1, os.SEEK_SET)
                if os.read(fd, 1) != b"\n":  # a writer died mid-line: close it, keep ours whole
                    data = b"\n" + data
            n = os.write(fd, data)
            while n < len(data):
                n += os.write(fd, data[n:])
    finally:
        os.close(fd)
    if not got:
        _log_error("timed", TimeoutError(f"{d / LOCK_NAME} not had in {LOCK_TIMEOUT:g} s; event written without it"))
    return f


def record(task: str, start: datetime, end: datetime, duration_s: float, exit: int | None, *,
           ledger: str | Path | None = None, **kw) -> dict | None:
    """make_event, then write_event unless BRAIN_TIMED=0; the event, None when it could not be made. Never raises:
    an error goes to ledger/errors.log."""
    try:
        ev = make_event(task, start, end, duration_s, exit, **kw)
        if os.environ.get("BRAIN_TIMED", "1") != "0":
            write_event(ev, ledger)
        return ev
    except Exception as exc:  # noqa: BLE001 - the ledger never breaks the timed work
        _log_error("timed", exc)
        return None


class timed(contextlib.ContextDecorator):
    """Time a block (``with timed("task"):``) or each call of a function (``@timed()``, ``@timed("task")``) into the
    ledger. The exit is 0, a SystemExit's code, 130 for KeyboardInterrupt, else 1 with ``error`` the exception's type;
    the exception goes on. ``event`` holds the event after a ``with`` block. Writing never raises; an unknown field
    raises TypeError at once."""

    def __init__(self, task: str | None = None, *, project: str | None = None, version: str | None = None,
                 ledger: str | Path | None = None, **fields):
        unknown = set(fields) - FIELDS
        if unknown:
            raise TypeError(f"timed: unknown field(s) {', '.join(sorted(unknown))} (allowed: {', '.join(sorted(FIELDS))})")
        self.task, self.project, self.version, self.ledger, self.fields = task, project, version, ledger, fields
        self.event: dict | None = None
        self._start: datetime | None = None
        self._t0 = 0.0

    def __call__(self, func):
        if self.task is None:
            self.task = f"{func.__module__}.{func.__qualname__}"
        return super().__call__(func)

    def _recreate_cm(self):  # a fresh timer per call: recursion and threads keep their own start
        return timed(self.task, project=self.project, version=self.version, ledger=self.ledger, **self.fields)

    def __enter__(self):
        if not self.task:
            raise TypeError("timed: a with block needs a task name")
        self._start, self._t0 = datetime.now(timezone.utc), time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        duration, end = time.perf_counter() - self._t0, datetime.now(timezone.utc)
        code, error = 0, None
        if exc_type is not None and issubclass(exc_type, SystemExit):
            c = exc.code
            code = c if isinstance(c, int) else 0 if c is None else 1
        elif exc_type is not None and issubclass(exc_type, KeyboardInterrupt):
            code, error = 130, "KeyboardInterrupt"
        elif exc_type is not None:
            code, error = 1, exc_type.__name__
        fields = dict(self.fields)
        if error:
            fields["error"] = error
        self.event = record(self.task, self._start, end, duration, code, project=self.project,
                            version=self.version, ledger=self.ledger, **fields)
        return False


# brain timed -- COMMAND

def _task_from(command: list[str], shell: bool = False) -> str:
    """The default task: the command line, its program without folder or extension (python, not C:/.../python.exe)."""
    words = " ".join(command).split() if shell else command
    return _clean(" ".join([Path(words[0]).stem or words[0], *words[1:]]), TASK_MAX) if words else "unnamed"


def _execute(command: list[str], shell: bool) -> tuple[int | None, str | None]:
    """Run ``command`` with this process's streams; (its exit code, why it did not finish normally)."""
    if shell:
        argv: str | list[str] = " ".join(command)
    else:
        exe = shutil.which(command[0])
        if not exe:
            return 127, "not found"
        argv = [exe, *command[1:]]
    try:
        proc = subprocess.Popen(argv, shell=shell)
    except OSError as exc:
        return 126, f"cannot run: {type(exc).__name__}"
    try:
        return proc.wait(), None
    except KeyboardInterrupt:  # the console sent it to the command too: let it finish, then kill it
        try:
            return proc.wait(timeout=INTERRUPT_GRACE), "interrupted"
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            proc.kill()
            return proc.wait(), "interrupted"


def run(command: list[str], task: str | None = None, project: str | None = None, version: str | None = None,
        shell: bool = False, quiet: bool = False, out=None) -> int:
    """``brain timed``: run ``command`` (its input and output untouched), write its event, return its exit code (a
    POSIX signal N as 128 + N). One line on stderr unless ``quiet``: the task, the duration and the exit."""
    out = out or sys.stderr
    command = list(command or [])
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("brain timed: no command (brain timed [--task T] -- COMMAND...)", file=out)
        return 2
    line = " ".join(command) if shell else subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
    task = task or _task_from(command, shell)
    start, t0 = datetime.now(timezone.utc), time.perf_counter()
    code, error = _execute(command, shell)
    duration, end = time.perf_counter() - t0, datetime.now(timezone.utc)
    ev = record(task, start, end, duration, code, project=project, version=version, command=line, error=error)
    if not quiet:
        print(f"timed: {ev['task'] if ev else task} {fmt_duration(duration)}, exit {code}"
              + (f" ({error})" if error else ""), file=out, flush=True)
    if code is None:
        return 1
    return 128 - code if code < 0 else code
