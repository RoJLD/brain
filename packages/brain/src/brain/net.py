"""One helper for the engine's external calls (wi-brain-net-resilience): a timeout, a retry with backoff and jitter,
and a circuit breaker remembered across runs, so that a service that is down costs one timeout per window, not one
per call, and the caller says what it skipped in one line.

A *service* is a short name the caller picks: ``gitnexus`` (its REST API and MCP endpoint), ``docker``,
``http:<host>`` (ntfy, Telegram), ``git-remote:<host or repo>`` (``git ls-remote``). The policy:

- **the timeout** stays the caller's (each call site keeps the one it had); this module only reads its outcome;
- **a quick failure** is retried :data:`RETRIES` times, after :func:`backoff` seconds: exponential
  (:data:`BACKOFF_S` doubled per attempt, capped at :data:`CAP_S`) with full jitter, so that several machines do
  not retry in step. For a call that may be repeated (a read: ``idempotent``), a quick failure is a refused or
  reset connection, a DNS miss, or an HTTP 429, 502, 503 or 504; for one that must not act twice (a POST that sends
  a notification or starts a job), only what proves the request was not handled: a refused connection, a DNS miss,
  an HTTP 429 or 503;
- **a timeout** is never retried: it already cost the whole wait;
- **the breaker**: a call whose service is down (a timeout, or a connection that failed past its retries) opens
  the service's breaker for :data:`WINDOW_S` seconds. While it is open, :func:`call` raises :class:`Unavailable` at
  once, without calling, and its text is the one line the caller prints (« gitnexus unavailable since 20:14
  (timed out); skipped until 20:19 »). The first call after the window goes through (half-open): an answer closes
  the breaker, a failure opens it for another window;
- **an answer** (any HTTP status, 429 and 5xx included once their retries are spent; a command's own non-zero
  exit; a missing program; a certificate refused) goes back to the caller unchanged and closes the breaker: the
  service is there, so a busy or rate-limited one never shuts its other calls;
- ``breaker=False``: the retry only, nothing checked or recorded (a poll inside a long job, a call the owner asked
  for by hand).

``$BRAIN_NET_BREAKER=off`` turns the breaker off for a run (every call is tried, nothing is recorded): a service
just restarted by hand need not wait for its window. :func:`ok` closes a breaker before an explicit retry
(``brain update`` reads the tags even when the cockpit's background check timed out a minute ago).

The breakers are a truth-local file, ``$BRAIN_HOME/net/breakers.json`` (brain.stateio, ``v`` 1; store ``net`` in
brain.classes, sealed): ``{service: {"since", "until", "why", "failures"}}``, written only when a breaker opens or
closes (a read-only command that meets a down service writes it too: the breaker is this module's state, not the
command's data). Losing it costs one timeout per service; a file this engine cannot write never fails a call.
"""

from __future__ import annotations

import os
import random
import socket
import ssl
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
RETRY_HTTP = {429, 502, 503, 504}   # retried on a read
UNHANDLED_HTTP = {429, 503}         # the request was not handled: retried on a POST too
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


def _reason(exc: BaseException) -> object:
    """What a URLError wraps (the exception itself otherwise)."""
    if isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError):
        return exc.reason
    return exc


def timed_out(exc: BaseException) -> bool:
    """Whether ``exc`` is a call that ran out of time."""
    if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError, socket.timeout)):
        return True
    reason = _reason(exc)
    return reason is not exc and (isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason))


def down(exc: BaseException) -> bool:
    """Whether ``exc`` says the service is not there: a timeout, a connection refused, reset or never made, a DNS
    miss. An HTTP status, a certificate refused or a missing program is an answer, not that."""
    if timed_out(exc):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return False
    reason = _reason(exc)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return False
    if reason is not exc:   # a URLError: the connection was not made, whatever its reason
        return True
    return isinstance(exc, (ConnectionError, socket.gaierror))


def quick(exc: BaseException, idempotent: bool = True) -> bool:
    """Whether ``exc`` is worth another try now (never a timeout): see the module's policy."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (RETRY_HTTP if idempotent else UNHANDLED_HTTP)
    if timed_out(exc) or not down(exc):
        return False
    if idempotent:
        return True
    reason = _reason(exc)
    return isinstance(reason, (ConnectionRefusedError, socket.gaierror))


def failure(exc: BaseException) -> bool:
    """Whether ``exc`` may pass if tried later (down, or a 429/5xx): what an outbox keeps."""
    return down(exc) or (isinstance(exc, urllib.error.HTTPError) and exc.code in RETRY_HTTP)


def backoff(attempt: int, base: float = BACKOFF_S, cap: float = CAP_S) -> float:
    """The wait before retry ``attempt`` (1 for the first): full jitter over an exponential ceiling."""
    return _random() * min(cap, base * (2 ** (attempt - 1)))


def _hm(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).astimezone().strftime("%H:%M")


def _why(exc: BaseException) -> str:
    if timed_out(exc):
        return "timed out"
    reason = _reason(exc)
    text = f"{type(reason).__name__}: {reason}" if isinstance(reason, BaseException) else \
        f"{type(exc).__name__}: {reason}"
    return text.splitlines()[0][:120] if text else type(exc).__name__


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
    """Open ``service``'s breaker for :data:`WINDOW_S` after a call that found it down; the line said from now on."""
    if not enabled():
        return ""
    state = stateio.load(path())
    now = _clock()
    prev = state.data.get(service) if isinstance(state.data.get(service), dict) else {}
    entry = {"since": prev.get("since") or now, "until": now + WINDOW_S,
             "why": exc if isinstance(exc, str) else _why(exc), "failures": int(prev.get("failures") or 0) + 1}
    state.data[service] = entry
    _save(state)
    return line(service, entry)


def ok(service: str) -> None:
    """Close ``service``'s breaker: it answered (or the owner asks for a retry). Writes only when one was recorded,
    and never moves an unreadable file (a read-only command calls it)."""
    if not enabled():
        return
    state = stateio.load(path(), aside=False)
    if service in state.data and state.writable:
        del state.data[service]
        _save(state)


def call(service: str, fn: Callable[[], T], *, retries: int = RETRIES, idempotent: bool = True,
         breaker: bool = True) -> T:
    """``fn()`` under ``service``'s breaker: skipped with :class:`Unavailable` while it is open, a quick failure
    retried with backoff and jitter, a timeout not retried; a last failure that says the service is down opens the
    breaker and is raised as it was. An answer (any other exception) closes the breaker and is raised unchanged.
    ``idempotent=False``: retried only when the request was surely not handled; ``breaker=False``: the retry only."""
    if breaker:
        why = blocked(service)
        if why:
            raise Unavailable(service, why)
    attempt = 0
    while True:
        try:
            out = fn()
        except Exception as exc:  # noqa: BLE001 (sorted below, then raised as it was)
            if attempt < retries and quick(exc, idempotent):
                attempt += 1
                _sleep(backoff(attempt))
                continue
            if breaker:
                if down(exc):
                    failed(service, exc)
                else:
                    ok(service)
            raise
        if breaker:
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
