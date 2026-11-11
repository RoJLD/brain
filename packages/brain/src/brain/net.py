"""One helper for the engine's external calls (wi-brain-net-resilience): a timeout, a retry with backoff and jitter,
and a circuit breaker remembered across runs, so that a service that is down costs one timeout per window, not one
per call, and the caller says what it skipped in one line.

A *service* is a short name the caller picks: ``gitnexus`` (its REST API and MCP endpoint), ``docker``, ``gh``,
``http:<host>`` (ntfy, Telegram), ``git-remote:<host or repo>`` (``git ls-remote``). The policy:

- **the timeout** stays the caller's (each call site keeps the one it had); this module only reads its outcome;
- **a quick failure** (a refused or reset connection, an HTTP 429, 502, 503 or 504) is retried :data:`RETRIES`
  times, after :func:`backoff` seconds: exponential (:data:`BACKOFF_S` doubled per attempt, capped at
  :data:`CAP_S`) with full jitter, so that several machines do not retry in step;
- **a timeout** is never retried: it already cost the whole wait;
- **the breaker**: a call that still fails that way (a timeout, or a quick failure past its retries) opens the
  service's breaker for :data:`WINDOW_S` seconds. While it is open, :func:`call` raises :class:`Unavailable` at
  once, without calling, and its text is the one line the caller prints (« gitnexus unavailable since 20:14
  (timed out); skipped until 20:19 »). The first call after the window goes through (half-open): a success closes
  the breaker, a failure opens it for another window;
- **anything else** (an HTTP 404, a command's own non-zero exit, a missing program) is the service's answer: it
  goes back to the caller unchanged, closes the breaker (the service answered) and is never retried.

``$BRAIN_NET_BREAKER=off`` turns the breaker off for a run (every call is tried, nothing is recorded): a service
just restarted by hand need not wait for its window.

The breakers are a truth-local file, ``$BRAIN_HOME/net/breakers.json`` (brain.stateio, ``v`` 1; store ``net`` in
brain.classes, sealed): ``{service: {"since", "until", "why", "failures"}}``, written only when a breaker opens or
closes. Losing it costs one timeout per service; a file this engine cannot write never fails a call.
"""

from __future__ import annotations

import os
import random
import socket
import subprocess
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

from . import paths, stateio

T = TypeVar("T")

RETRIES = 2            # quick failures retried this many times (3 tries in all)
BACKOFF_S = 0.5        # the first retry's ceiling, doubled per attempt
CAP_S = 8.0            # no wait above this
WINDOW_S = 300.0       # how long an open breaker skips its service
SWITCH = "BRAIN_NET_BREAKER"   # off: no breaker for this run
RETRY_HTTP = {429, 502, 503, 504}
FILE = "breakers.json"

_sleep = time.sleep    # the tests replace these
_clock = time.time
_random = random.random


class Unavailable(OSError):
    """A service whose breaker is open: the call was skipped. Its text is the line to print."""

    def __init__(self, service: str, line: str):
        super().__init__(line)
        self.service = service
        self.line = line

    def __str__(self) -> str:
        return self.line


def path() -> Path:
    return paths.brain_home() / "net" / FILE


def enabled() -> bool:
    return (os.environ.get(SWITCH) or "").strip().lower() not in ("off", "0", "no", "false")


def timed_out(exc: BaseException) -> bool:
    """Whether ``exc`` is a call that ran out of time."""
    if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None) if isinstance(exc, urllib.error.URLError) else None
    return isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason or "")


def quick(exc: BaseException) -> bool:
    """Whether ``exc`` is a failure worth another try soon: a connection refused or reset, a DNS miss, an HTTP 429
    or 5xx gateway answer. An HTTP status otherwise is the service's answer."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRY_HTTP
    if isinstance(exc, urllib.error.URLError):
        return not timed_out(exc)
    return isinstance(exc, (ConnectionError, socket.gaierror))


def failure(exc: BaseException) -> bool:
    """Whether ``exc`` counts against the service's breaker."""
    return timed_out(exc) or quick(exc)


def backoff(attempt: int, base: float = BACKOFF_S, cap: float = CAP_S) -> float:
    """The wait before retry ``attempt`` (1 for the first): full jitter over an exponential ceiling."""
    return _random() * min(cap, base * (2 ** (attempt - 1)))


def _hm(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).astimezone().strftime("%H:%M")


def _why(exc: BaseException) -> str:
    if timed_out(exc):
        return "timed out"
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    reason = getattr(exc, "reason", None)
    text = f"{type(exc).__name__}: {reason if reason is not None else exc}"
    return text.splitlines()[0][:120] if text else type(exc).__name__


def _load() -> stateio.State:
    return stateio.load(path())


def _save(state: stateio.State) -> None:
    try:
        stateio.save(state)
    except (stateio.StateError, OSError):   # a breaker never fails a call: it then costs a timeout per call
        pass


def line(service: str, entry: dict) -> str:
    """The one line said when ``service`` is skipped."""
    since, until = entry.get("since"), entry.get("until")
    when = f" since {_hm(since)}" if isinstance(since, (int, float)) else ""
    then = f"; skipped until {_hm(until)}" if isinstance(until, (int, float)) else ""
    return f"{service} unavailable{when} ({entry.get('why') or 'failed'}){then} ({SWITCH}=off to try anyway)"


def blocked(service: str) -> str:
    """The line to print when ``service``'s breaker is open ('' when a call may go: closed, half-open, or off)."""
    if not enabled():
        return ""
    entry = stateio.load(path(), aside=False).data.get(service)
    if isinstance(entry, dict) and isinstance(entry.get("until"), (int, float)) and _clock() < entry["until"]:
        return line(service, entry)
    return ""


def failed(service: str, exc: BaseException | str) -> str:
    """Open ``service``'s breaker for :data:`WINDOW_S` after a failed call; the line said from now on."""
    if not enabled():
        return ""
    state = _load()
    now = _clock()
    prev = state.data.get(service) if isinstance(state.data.get(service), dict) else {}
    entry = {"since": prev.get("since") or now, "until": now + WINDOW_S,
             "why": exc if isinstance(exc, str) else _why(exc), "failures": int(prev.get("failures") or 0) + 1}
    state.data[service] = entry
    _save(state)
    return line(service, entry)


def ok(service: str) -> None:
    """Close ``service``'s breaker: it answered. Writes only when one was recorded."""
    if not enabled():
        return
    state = _load()
    if service in state.data:
        del state.data[service]
        _save(state)


def call(service: str, fn: Callable[[], T], *, retries: int = RETRIES) -> T:
    """``fn()`` under ``service``'s breaker: skipped with :class:`Unavailable` while it is open, a quick failure
    retried with backoff and jitter, a timeout not retried; the last failure opens the breaker and is raised as it
    was. Another exception (the service's own answer) closes the breaker and is raised unchanged."""
    why = blocked(service)
    if why:
        raise Unavailable(service, why)
    attempt = 0
    while True:
        try:
            out = fn()
        except Exception as exc:  # noqa: BLE001 (sorted below, then raised as it was)
            if not failure(exc):
                ok(service)
                raise
            if quick(exc) and attempt < retries:
                attempt += 1
                _sleep(backoff(attempt))
                continue
            failed(service, exc)
            raise
        ok(service)
        return out


def run(service: str, argv: list[str], *, timeout: float, **kwargs) -> subprocess.CompletedProcess:
    """``subprocess.run(argv, timeout=timeout, **kwargs)`` under ``service``'s breaker: a timeout opens it (raised
    as ``subprocess.TimeoutExpired``), a skipped call raises :class:`Unavailable` (an OSError, like a missing
    program); the exit code is the command's answer, never retried."""
    return call(service, lambda: subprocess.run(argv, timeout=timeout, **kwargs), retries=0)


def status() -> dict[str, dict]:
    """The breakers recorded, open or not ({service: entry, "open": bool})."""
    now = _clock()
    return {s: {**e, "open": isinstance(e.get("until"), (int, float)) and now < e["until"]}
            for s, e in stateio.load(path(), aside=False).data.items() if isinstance(e, dict)}
