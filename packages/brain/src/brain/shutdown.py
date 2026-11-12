"""Graceful shutdown and single-instance locks (wi-brain-graceful-shutdown; the client standards' pillars 4.1 and 4.2).

A command stopped by a signal finishes or rolls back the write it is in, then stops with its locks released:

- :func:`graceful` (``brain.cli.main`` runs every command in it, so the long ones, sync, refresh, coverage, vault
  reseal, among them): SIGINT (Ctrl+C), SIGTERM, SIGHUP (POSIX) and SIGBREAK (Ctrl+Break on Windows) raise
  :class:`Stopped` in the main thread, a ``KeyboardInterrupt``, so every ``finally`` and ``with`` on the way out runs: a
  lock is released, an atomic write's temporary file goes (the file is left as it was: rolled back). Without it SIGTERM,
  SIGHUP and SIGBREAK end the process at once, and nothing on the way out runs. The command says which signal stopped
  it, then dies by it on POSIX (:func:`die`: the shell sees 128 + its number) or exits 128 + its number on Windows. ``TerminateProcess`` (``taskkill /F``, the Task Manager)
  and SIGKILL cannot be trapped: the atomic writes are what keeps a file whole then.
- :func:`critical`: a signal that arrives inside it waits until it ends (the write finishes), then stops the command.
  The engine's writers hold one around their write: ``brain.timing.append_text`` (every ledger line),
  ``brain.stateio.write_atomic`` (every state file). Outside :func:`graceful` it only counts (the signal's default
  stands).
- :func:`single_instance`: an exclusive lock on ``<BRAIN_HOME>/locks/<name>.lock``, held while the block runs (the OS
  drops it when the process dies, so a stale lock never stays); a second holder gets :class:`Busy`, with the holder's
  pid and start read from ``<name>.json`` beside it. The interactive cockpit (``brain tui``) and the scheduled alerts
  pass (``brain alerts --notify``) take one.

Standard library only (a hook may import this module through brain.timing).
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import paths

# the signals trapped where they exist: SIGHUP is POSIX's, SIGBREAK Windows' Ctrl+Break
SIGNALS = tuple(getattr(signal, n) for n in ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK") if hasattr(signal, n))

_pending: list[int] = []   # a signal that arrived inside a critical section, raised when it ends
_depth = [0]               # the main thread's critical sections open
_installed = [False]       # graceful()'s handlers are in place


class Stopped(KeyboardInterrupt):
    """The command was stopped by ``signum``; ``exit_code`` is 128 + its number."""

    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum
        self.exit_code = 128 + int(signum)

    @property
    def name(self) -> str:
        try:
            return signal.Signals(self.signum).name
        except ValueError:
            return f"signal {self.signum}"


class Busy(RuntimeError):
    """Another process holds the single-instance lock; ``holder`` is what it wrote (pid, at, what), maybe empty."""

    def __init__(self, name: str, holder: dict):
        self.name, self.holder = name, holder
        pid, at = holder.get("pid"), holder.get("at")
        who = f" (pid {pid}" + (f", since {at}" if at else "") + ")" if pid else ""
        super().__init__(f"another {holder.get('what') or name} runs on this machine{who}")


def _main_thread() -> bool:
    return threading.current_thread() is threading.main_thread()


def _handler(signum, _frame):
    if _depth[0]:
        if signum not in _pending:
            _pending.append(signum)
        return
    raise Stopped(signum)


@contextlib.contextmanager
def graceful():
    """Trap :data:`SIGNALS` while the block runs (the main thread only; elsewhere, or nested, it changes nothing):
    each raises :class:`Stopped` there, or when the critical section it arrived in ends. The handlers before are put
    back after."""
    if not _main_thread() or _installed[0]:
        yield
        return
    before = {}
    for s in SIGNALS:
        try:
            before[s] = signal.signal(s, _handler)
        except (OSError, ValueError, RuntimeError):  # not settable here (an embedded interpreter): left as it was
            pass
    _installed[0] = True
    try:
        yield
    finally:
        _installed[0] = False
        _pending.clear()
        for s, h in before.items():
            try:
                signal.signal(s, h if h is not None else signal.SIG_DFL)
            except (OSError, ValueError, RuntimeError):
                pass


@contextlib.contextmanager
def critical():
    """A write that a signal must not cut: one that arrives meanwhile is raised when the block ends (in the main
    thread; another thread's block only runs, the signal is the main thread's)."""
    if not _main_thread():
        yield
        return
    _depth[0] += 1
    try:
        yield
    finally:
        _depth[0] -= 1
        if not _depth[0] and _pending:
            signum = _pending.pop(0)
            _pending.clear()
            # the write raised meanwhile (a PermissionError a caller would catch): the stop still wins, chained to
            # it; an interrupt already on its way stands
            if not isinstance(sys.exc_info()[1], KeyboardInterrupt):
                raise Stopped(signum)


def die(exc: Stopped) -> None:
    """POSIX: end the process by the signal itself, its default action restored, once the way out has run: a shell
    stops a loop on a child killed by SIGINT, a supervisor counts a SIGTERM death as a stop, not a failure. Windows
    has no such death: the caller returns ``exc.exit_code``."""
    if os.name == "nt":
        return
    try:
        signal.signal(exc.signum, signal.SIG_DFL)
        os.kill(os.getpid(), exc.signum)
    except (OSError, ValueError):
        pass


def locks_dir() -> Path:
    return paths.brain_home() / "locks"


def holder(name: str) -> dict:
    """What the lock's holder wrote (pid, at, what); {} when nothing readable is there."""
    try:
        data = json.loads((locks_dir() / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@contextlib.contextmanager
def single_instance(name: str, what: str = ""):
    """Hold ``<BRAIN_HOME>/locks/<name>.lock`` while the block runs; :class:`Busy` when another process holds it.
    ``what`` names the holder in the refusal (``brain tui``)."""
    from . import timing   # the ledger's lock primitives (msvcrt.locking on Windows, flock elsewhere)

    d = locks_dir()
    d.mkdir(parents=True, exist_ok=True)
    fd = os.open(d / f"{name}.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    try:
        if not timing._try_lock(fd):
            raise Busy(name, holder(name))
        try:
            at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            try:
                (d / f"{name}.json").write_text(json.dumps({"pid": os.getpid(), "at": at, "what": what or name}),
                                                encoding="utf-8")
            except OSError:
                pass
            yield
        finally:
            timing._unlock(fd)
    finally:
        os.close(fd)
