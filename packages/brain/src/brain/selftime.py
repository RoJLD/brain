"""The engine times itself (wi-brain-self-timing; spec-brain-telemetry-perf §3.4 rank 2 and §4.2, the first stage of
the opt-in telemetry): every ``brain`` command and every hook writes one exec event of the event schema
(``schemas/event.schema.json``), and every error a hook or a command catches becomes an error event. Local only, zero
token; ``brain perf --engine`` (brain.perf) and ``brain alerts`` (brain.alerts.engine_alerts) read them back.

- An exec event: project ENGINE, task ``brain <command> [<subcommand>]`` (cli.main) or ``hook <name> [<argument>]``
  (the hooks' Python entries, :class:`run`), version the engine's (``brain.__version__``), its duration and exit; a
  run during which an error was caught carries that error's class in ``error``.
- An error event: the same envelope, code the exception's class, severity error, ``details.where`` the engine's
  ``module:function`` where it was raised (the innermost frame of the brain package, else the innermost one); never
  its message, which may hold a path or a command (the token ledger's rule, ST-7). The errors reach it through the
  shared sink, :func:`brain.capture._log_error` (which keeps its text line in ``ledger/errors.log``), and through
  :class:`run` for an error nothing caught.

The events go to ``$BRAIN_HOME/ledger/engine/``, apart from the projects' own (``brain timed``, the ops error events,
the alerts): at the owner's pace a hook runs about 7,500 times a day, ~1.7 MB of lines that every reader of the
projects' ledger (brain alerts, brain status) would otherwise parse.

  exec-<yyyy-mm>.jsonl       the Python writers, under the ledger's lock (brain.timing.append)
  exec-bash-<yyyy-mm>.jsonl  the hooks' bash fast paths (hooks/common.sh): one append each, which bash opens
                             O_APPEND and Windows makes atomic (2,400 lines of 8 writers whole, measured); never the
                             locked writers' file, since there the C runtime's O_APPEND is a seek then a write that a
                             bash append can slip between
  error-<yyyy-mm>.jsonl      the error events

When a month's first event starts a new file, the files older than KEEP_MONTHS months go. A hook's duration runs from
its bash script's first line (``$EPOCHREALTIME``, passed in ``BRAIN_HOOK_T0``) to the end of its Python, so the
interpreter's start is counted; bash's own start (~0.12 s on Windows) is not. ``BRAIN_SELFTIME=0`` turns the writing
off (the tests run so). Writing never fails the timed work and never raises: an error goes to ``ledger/errors.log``.
Standard library only, and light to import: a hook pays for it on every tool call.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, _started, paths, timing

ENGINE = "brain"         # the project of the engine's own events
FOLDER = "engine"        # under the ledger
KEEP_MONTHS = 3
T0_ENV = "BRAIN_HOOK_T0"  # the hook's bash start, epoch seconds ($EPOCHREALTIME: a dot or the locale's comma)
T0_MAX_S = 600.0          # an older or future start is not this run's: the Python start is used
PACKAGE = __name__.rpartition(".")[0]

_stack: list["run"] = []  # the runs being timed in this process, innermost last
_writing = False          # an error while writing an event is logged to errors.log only: no event about an event


def on() -> bool:
    return os.environ.get("BRAIN_SELFTIME", "1") != "0"


def engine_dir() -> Path:
    return paths.ledger_dir() / FOLDER


# Wrappers an error only passes through: brain.nowindow's Popen.__init__ wraps every child the engine starts, so a
# child's own error (a missing cwd) is its caller's, never nowindow's.
TRANSPARENT = ("brain.nowindow:",)


def where(exc: BaseException) -> str:
    """``module:function`` of the innermost frame of the brain package in ``exc``'s traceback, else of the innermost
    frame; '' without a traceback."""
    tb, mine, last = exc.__traceback__, "", ""
    while tb is not None:
        f = tb.tb_frame
        name = f"{f.f_globals.get('__name__', '?')}:{f.f_code.co_name}"
        last = name
        if (name == PACKAGE or name.startswith(PACKAGE + ".")) and not name.startswith(TRANSPARENT):
            mine = name
        tb = tb.tb_next
    return mine or last


def _bare(exc_type: type) -> str:
    return exc_type.__name__ if exc_type.__module__ in ("builtins", "__main__") else \
        f"{exc_type.__module__}.{exc_type.__qualname__}"


def _write(kind: str, event: dict, now: datetime) -> None:
    global _writing
    if _writing or not on():
        return
    _writing = True
    try:
        d = engine_dir()
        f = d / f"{kind}-{now:%Y-%m}.jsonl"
        if not f.exists():
            prune(d, now)
        timing.append(f, event)
    except Exception as exc:  # noqa: BLE001 - the timing never breaks the timed work
        timing._log_error("selftime", exc)
    finally:
        _writing = False


def prune(d: Path, now: datetime) -> list[Path]:
    """Remove the engine's event files of the months before the last KEEP_MONTHS (this one counted); the removed."""
    y, m = now.year, now.month - (KEEP_MONTHS - 1)
    while m < 1:
        y, m = y - 1, m + 12
    oldest, gone = f"{y:04d}-{m:02d}", []
    for f in d.glob("*.jsonl") if d.is_dir() else ():
        month = f.stem[-7:]
        if len(month) == 7 and month[4] == "-" and month < oldest:
            try:
                f.unlink()
                gone.append(f)
            except OSError:
                pass
    return gone


def _envelope(kind: str, task: str, now: datetime) -> dict:
    return {"v": 1, "kind": kind, "at": timing.iso(now), "host": timing.host(), "project": ENGINE,
            "task": task[:timing.TASK_MAX] or "unnamed", "version": __version__}


def error(exc: BaseException, task: str | None = None) -> None:
    """Write the error event of ``exc``, caught in ``task`` (default: the run being timed, else 'brain'). Never
    raises."""
    try:
        if _writing:
            return
        current = _stack[-1] if _stack else None
        if current is not None and current.caught is None:
            current.caught = _bare(type(exc))
        now = datetime.now(timezone.utc)
        ev = _envelope("error", task or (current.task if current else "brain"), now)
        ev.update(code=_bare(type(exc)), severity="error", pid=os.getpid())
        at = where(exc)
        if at:
            ev["details"] = {"where": at}
        _write("error", ev, now)
    except Exception:  # noqa: BLE001
        pass


def _hook_start(now_epoch: float) -> float | None:
    raw = os.environ.get(T0_ENV, "").strip().replace(",", ".")
    try:
        t0 = float(raw)
    except ValueError:
        return None
    return t0 if 0 <= now_epoch - t0 <= T0_MAX_S else None


class run:
    """Time the engine's run of ``task`` (``with run("hook guard shell"):``) into its exec event. The exit is 0, a
    SystemExit's code (1 for a message), 130 for KeyboardInterrupt, else 1 and an error event for the exception, which
    goes on. The start: ``hook=True``, the hook's bash start (BRAIN_HOOK_T0) when it is set and recent, else the
    engine's import; ``hook=False`` (a command), the engine's import (``brain._started``), so its imports count. Never
    raises."""

    def __init__(self, task: str, *, hook: bool = False, from_import: bool = True):
        self.task, self.hook, self.from_import = task, hook, from_import
        self.caught: str | None = None
        self.event: dict | None = None

    def __enter__(self):
        self._epoch, self._t0 = time.time(), time.perf_counter()
        bash = _hook_start(self._epoch) if self.hook else None
        if bash is not None:
            self._before = self._epoch - bash
        else:
            self._before = self._t0 - _started[1] if self.from_import else 0.0
        _stack.append(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if _stack and _stack[-1] is self:
                _stack.pop()
            duration = time.perf_counter() - self._t0 + self._before
            code, why = 0, self.caught
            if exc_type is not None and issubclass(exc_type, SystemExit):
                c = exc.code
                code = c if isinstance(c, int) else 0 if c is None else 1
            elif exc_type is not None and issubclass(exc_type, KeyboardInterrupt):
                code, why = 130, "KeyboardInterrupt"
            elif exc_type is not None:
                code, why = 1, _bare(exc_type)
                error(exc, self.task)
            # start and end from one clock, rounded the same way: datetime.now() against fromtimestamp(time.time())
            # put the end 1 ms before the start now and then; the end is never before the run's own start
            now = datetime.fromtimestamp(max(time.time(), self._epoch), timezone.utc)
            ev = _envelope("exec", self.task, now)
            start = datetime.fromtimestamp(self._epoch - self._before, timezone.utc)
            ev.update(start=timing.iso(start), end=ev["at"], duration_s=round(max(duration, 0.0), 3), exit=code,
                      pid=os.getpid())
            if why:
                ev["error"] = why[:timing.ERROR_MAX]
            self.event = ev
            _write("exec", ev, now)
        except Exception:  # noqa: BLE001
            pass
        return False


def hook(task: str, main, *args) -> int:
    """A hook's Python entry: ``main(*args)`` timed as ``task``; its exit code (a hook's main never raises; if it
    does, the call still goes through: 0)."""
    with run(task, hook=True):
        try:
            return main(*args)
        except Exception as exc:  # noqa: BLE001 - a hook never breaks a session
            error(exc, task)
            return 0


def command_task(args) -> str:
    """``brain <command> [<subcommand>]`` from the parsed arguments: the command, then its family's subcommand
    (``<command>_cmd``, record's kind) when it has one."""
    cmd = getattr(args, "cmd", None) or "brain"
    sub = getattr(args, f"{cmd}_cmd", None) or (getattr(args, "record_kind", None) if cmd == "record" else None)
    return " ".join(["brain", cmd, *([sub] if isinstance(sub, str) and sub else [])])
