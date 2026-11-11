"""The sealed local outbox of outbound calls (wi-brain-outbox): what could not leave is kept, then sent again.

A call that leaves the machine and fails (a notification whose every channel failed; later the shareboard and the
telemetry reports, as their callers come) is queued here instead of being lost, under an *idempotency key* the
caller computes from what it sends: queuing the same key twice keeps one entry, and a fresh delivery of the same
content drops the queued copy (:func:`drop`), so nothing is sent twice by the outbox itself.

:func:`replay` runs inside the existing passes (the alerts pass, ``brain alerts --notify``: no scheduled task of its
own). Each entry due is handed to its kind's handler (``{kind: handler(payload) -> detail}``, given by the pass): a
handler that returns has delivered it (dropped from the outbox); one that raises has not, and the entry waits
:func:`wait` seconds more (exponential from :data:`BASE_S`, capped at :data:`CAP_S`, full jitter: brain.net's
backoff). An entry past :data:`MAX_TRIES` tries or older than :data:`MAX_AGE` is given up, said in one line. A kind
the pass has no handler for waits untouched.

The outbox is a truth-local file, ``$BRAIN_HOME/outbox/queue.json`` (brain.stateio, ``v`` 1; store ``outbox`` in
brain.classes, sealed: never in git, off the machine only sealed)::

    {"<key>": {"kind": "notify", "payload": {...}, "at": "<queued, UTC>", "tries": 0, "next": "<UTC>", "why": "..."}}

Its writes go through brain.stateio: a newer brain's file is read-only here (a put then says so and keeps nothing),
an unreadable one set aside.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping

from . import net, paths, stateio

FILE = "queue.json"
BASE_S = 300.0                  # the first wait: the next pass or so
CAP_S = 6 * 3600.0              # no wait above 6 h
MAX_TRIES = 12
MAX_AGE = timedelta(days=7)

Handler = Callable[[dict], str]


def path() -> Path:
    return paths.brain_home() / "outbox" / FILE


def key_of(*parts: object) -> str:
    """An idempotency key: the same content, the same key."""
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _at(text: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def wait(tries: int) -> float:
    """Seconds before the next try of an entry tried ``tries`` times."""
    return net.backoff(max(1, tries), BASE_S, CAP_S)


def put(kind: str, key: str, payload: dict, why: str = "", *, now: datetime | None = None) -> str:
    """Queue ``payload`` under ``key``: '' when queued or already there, else why it could not be kept."""
    now = now or datetime.now(timezone.utc)
    state = stateio.load(path())
    if key in state.data:
        return ""
    state.data[key] = {"kind": kind, "payload": payload, "at": _iso(now), "tries": 0,
                       "next": _iso(now + timedelta(seconds=wait(1))), "why": why[:200]}
    try:
        stateio.save(state)
    except (stateio.StateError, OSError) as exc:
        return f"outbox: not kept ({exc})"
    return ""


def drop(key: str) -> bool:
    """Remove ``key`` (delivered by another way); whether it was there. Never fails the caller."""
    state = stateio.load(path(), aside=False)
    if key not in state.data:
        return False
    state = stateio.load(path())
    state.data.pop(key, None)
    try:
        stateio.save(state)
    except (stateio.StateError, OSError):
        return False
    return True


def pending() -> dict[str, dict]:
    """The entries waiting, by key (read only)."""
    return {k: e for k, e in stateio.load(path(), aside=False).data.items() if isinstance(e, dict)}


def replay(handlers: Mapping[str, Handler], *, now: datetime | None = None, dry_run: bool = False,
           limit: int = 50) -> list[str]:
    """Hand each entry due to its kind's handler, oldest first, at most ``limit``; the lines to print."""
    now = now or datetime.now(timezone.utc)
    state = stateio.load(path(), aside=not dry_run)
    if not state.data:
        return []
    lines: list[str] = []
    changed = False
    due = sorted((e.get("at") or "", k) for k, e in state.data.items()
                 if isinstance(e, dict) and e.get("kind") in handlers and (_at(e.get("next")) or now) <= now)
    for _, key in due[:limit]:
        e = state.data[key]
        kind = e["kind"]
        if dry_run:
            lines.append(f"outbox: would send {kind} {key} (queued {e.get('at')}, tried {e.get('tries', 0)})")
            continue
        try:
            detail = handlers[kind](e.get("payload") or {})
        except Exception as exc:  # noqa: BLE001 (a handler's failure keeps the entry for the next pass)
            e["tries"] = int(e.get("tries") or 0) + 1
            e["why"] = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
            queued = _at(e.get("at")) or now
            if e["tries"] >= MAX_TRIES or now - queued > MAX_AGE:
                del state.data[key]
                lines.append(f"outbox: gave up {kind} {key} after {e['tries']} tries since {e.get('at')}: {e['why']}")
            else:
                e["next"] = _iso(now + timedelta(seconds=wait(e["tries"] + 1)))
                lines.append(f"outbox: {kind} {key} not sent ({e['why']}); next try after {e['next']}")
        else:
            del state.data[key]
            lines.append(f"outbox: sent {kind} {key} queued {e.get('at')}" + (f" ({detail})" if detail else ""))
        changed = True
    if changed:
        try:
            stateio.save(state)
        except (stateio.StateError, OSError) as exc:
            lines.append(f"outbox: not saved ({exc})")
    return lines


def status(now: datetime | None = None) -> dict:
    """{waiting, oldest, kinds}: what ``brain notify status`` shows."""
    rows = pending()
    ats = sorted(str(e.get("at") or "") for e in rows.values())
    kinds: dict[str, int] = {}
    for e in rows.values():
        kinds[str(e.get("kind"))] = kinds.get(str(e.get("kind")), 0) + 1
    return {"waiting": len(rows), "oldest": ats[0] if ats else "", "kinds": kinds}


def line(s: dict) -> str:
    """One line ('' when nothing waits)."""
    if not s["waiting"]:
        return ""
    kinds = ", ".join(f"{n} {k}" for k, n in sorted(s["kinds"].items()))
    return f"outbox: {s['waiting']} waiting ({kinds}), the oldest queued {s['oldest']}; sent again by the alerts pass"
