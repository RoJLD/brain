"""A virtual clock and injected faults, honoured by the shared helpers (wi-brain-fault-injection;
spec-brain-client-standards 3, « systemic testability »), so that the command line and the suite play a failure or a
date end to end, without a mock in the code under test.

**The clock** (``$BRAIN_NOW``): :func:`now` and :func:`time` are the engine's « now » wherever a shared helper reads
it (brain.stateio's stamps and log months, brain.net's breaker windows, brain.quiet, the ``_now`` helpers of the
modules that keep one). Unset, they are the real clock. Set, it is either

- a point in time, frozen: ``2030-01-31`` (midnight UTC), ``2030-01-31T22:00`` or ``2030-01-31T22:00:00Z`` (a time
  without a zone is UTC; ``+01:00`` is honoured);
- a shift of the real clock, which keeps running: ``+3d``, ``-2h``, ``+90m``, ``+30s`` (``w`` for weeks).

**The faults** (``$BRAIN_FAULT``): a comma-separated list of ``<point>[@<glob>]:<kind>``. The glob narrows the fault
to the files (a path, matched against the whole path written with ``/`` and against the file's name) or the services
(brain.net's names: ``gitnexus``, ``github``, ``http:<host>``, ``git-remote:<repo>``) it names; without it every one
is hit. The points and their kinds:

- ``write`` (brain.stateio.write_atomic, through which every truth-local and foreign file is written):
  ``disk-full`` writes half of the temporary file then raises ``OSError(ENOSPC)``: the temporary file goes, the file
  is left as it was; ``killed`` writes and syncs the temporary file, then ends the process with exit code
  :data:`KILLED_EXIT` before the move, as a kill would: the file is left as it was, the temporary file stays;
- ``read`` (brain.stateio's reads: :func:`brain.stateio.load`, its set-aside check, :func:`brain.stateio.read_foreign`):
  ``corrupt`` reads the first half of the file's bytes followed by a byte that is not UTF-8. The file on disk is never
  changed: a truth-local file is then set aside (the copy holds the real bytes), a foreign one refused;
- ``net`` (brain.net.call and brain.net.run): ``timeout`` raises the timeout the call would end with
  (``subprocess.TimeoutExpired`` for a command, ``TimeoutError`` otherwise) without calling: never retried, and the
  service's breaker opens as after a real one; ``refused`` raises ``ConnectionRefusedError``: retried with backoff,
  then the breaker opens.

Each injected fault says so on stderr (« brain: BRAIN_FAULT write:killed on <path> »). A value this module cannot read
(an unknown point or kind, a clock that is not a date) raises :class:`FaultError`; the command line refuses to run
with it (exit 2) rather than play a different failure than the one asked. Both variables belong to the suite and to
the owner's terminal: the hermetic tests clear every ``BRAIN_*`` variable, so a test sets them itself.
"""

from __future__ import annotations

import errno
import fnmatch
import os
import re
import sys
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW_ENV = "BRAIN_NOW"
FAULT_ENV = "BRAIN_FAULT"
KILLED_EXIT = 137   # 128 + SIGKILL, what a shell reports for a killed process
KINDS: dict[str, tuple[str, ...]] = {
    "write": ("disk-full", "killed"),
    "read": ("corrupt",),
    "net": ("timeout", "refused"),
}
_SHIFT = re.compile(r"^([+-])\s*(\d+(?:\.\d+)?)\s*(s|m|h|d|w)$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}
_clocks: dict[str, "datetime | timedelta"] = {}       # $BRAIN_NOW's text -> what it means, per process
_lists: dict[str, list[tuple[str, str, str]]] = {}   # $BRAIN_FAULT's text -> its faults, per process
_said: set[tuple[str, str, str]] = set()               # the faults already said on stderr, per process


class FaultError(ValueError):
    """``$BRAIN_NOW`` or ``$BRAIN_FAULT`` holds a value this engine cannot read."""


# --- the clock ---

def _clock(text: str) -> datetime | timedelta:
    """A point in time (aware, UTC) or a shift of the real clock."""
    if text in _clocks:
        return _clocks[text]
    m = _SHIFT.match(text)
    if m:
        out: datetime | timedelta = timedelta(seconds=float(m.group(2)) * _UNITS[m.group(3)])
        if m.group(1) == "-":
            out = -out
    else:
        try:
            t = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
        except ValueError:
            raise FaultError(f"{NOW_ENV}={text!r}: a date (2030-01-31), a time (2030-01-31T22:00:00Z) or a shift "
                             "of the real clock (+3d, -2h, +90m, +30s, +1w)") from None
        out = (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    _clocks[text] = out
    return out


def virtual() -> bool:
    """Whether ``$BRAIN_NOW`` sets the clock."""
    return bool(os.environ.get(NOW_ENV, "").strip())


def now() -> datetime:
    """The engine's now, aware and in UTC: ``$BRAIN_NOW``'s when it is set, else the real clock's."""
    text = os.environ.get(NOW_ENV, "").strip()
    real = datetime.now(timezone.utc)
    if not text:
        return real
    v = _clock(text)
    return real + v if isinstance(v, timedelta) else v


def time() -> float:
    """:func:`now` as seconds since the epoch (``time.time()``'s unit)."""
    text = os.environ.get(NOW_ENV, "").strip()
    if not text:
        return _time.time()
    v = _clock(text)
    return _time.time() + v.total_seconds() if isinstance(v, timedelta) else v.timestamp()


# --- the faults ---

def _faults(text: str) -> list[tuple[str, str, str]]:
    """``$BRAIN_FAULT`` as (point, glob, kind) triples; FaultError on a value this module cannot read."""
    if text in _lists:
        return _lists[text]
    out = []
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        head, sep, kind = part.rpartition(":")
        point, _, glob = head.partition("@")
        point, glob, kind = point.strip(), glob.strip(), kind.strip()
        if not sep or point not in KINDS or kind not in KINDS[point]:
            known = "; ".join(f"{p}: {', '.join(k)}" for p, k in KINDS.items())
            raise FaultError(f"{FAULT_ENV}={text!r}: {part!r} is not <point>[@<glob>]:<kind> ({known})")
        out.append((point, glob, kind))
    _lists[text] = out
    return out


def _matches(glob: str, target: str) -> bool:
    if not glob:
        return True
    name = target.rsplit("/", 1)[-1]
    return fnmatch.fnmatchcase(target, glob) or fnmatch.fnmatchcase(name, glob)


def fault(point: str, target: str | os.PathLike) -> str:
    """The kind of fault ``$BRAIN_FAULT`` injects at ``point`` for ``target`` (a path or a service name); '' when
    none."""
    text = os.environ.get(FAULT_ENV, "").strip()
    if not text:
        return ""
    t = Path(target).as_posix() if isinstance(target, os.PathLike) else str(target).replace("\\", "/")
    for p, glob, kind in _faults(text):
        if p == point and _matches(glob, t):
            return kind
    return ""


def say(point: str, kind: str, target) -> None:
    """One line on stderr per fault and target, the first time it is injected in this process."""
    key = (point, kind, str(target))
    if key in _said:
        return
    _said.add(key)
    print(f"brain: {FAULT_ENV} {point}:{kind} on {target}", file=sys.stderr)


def check() -> None:
    """Read both variables once: :class:`FaultError` when one holds a value this module cannot read (the command line
    calls it before a command runs)."""
    text = os.environ.get(NOW_ENV, "").strip()
    if text:
        _clock(text)
    text = os.environ.get(FAULT_ENV, "").strip()
    if text:
        _faults(text)


# --- what the shared helpers call ---

def on_read(path: Path, blob: bytes) -> bytes:
    """The bytes a read of ``path`` returns: ``blob``, or its corrupt form under ``read:corrupt``."""
    if fault("read", path) != "corrupt":
        return blob
    say("read", "corrupt", path)
    return blob[: len(blob) // 2] + b"\xff"


def disk_full(path: Path) -> OSError:
    return OSError(errno.ENOSPC, f"{os.strerror(errno.ENOSPC)} ({FAULT_ENV})", str(path))


def killed(path: Path) -> None:
    """End the process as a kill would: no cleanup, no ``finally``, no buffered output beyond what is flushed here."""
    say("write", "killed", path)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
    os._exit(KILLED_EXIT)


def net_fault(service: str) -> str:
    """The kind injected on a call to ``service`` ('' when none), said on stderr."""
    kind = fault("net", service)
    if kind:
        say("net", kind, service)
    return kind
