"""Quiet mode (wi-brain-quiet-mode): moments with no interruption. ``brain quiet --for 2h`` or a project's declared
``notify: quiet_hours: "22:00-07:00"`` (local time) holds every notification below ``critical``; a critical one still
goes through. What was held is summed up in one message per project when the quiet ends.

Quiet silences notifications and nothing else. No task is paused, no scheduled task is disabled and no window is
opened or closed: a collector, whose data cannot be recovered, runs on, and the alerts pass keeps recording what it
finds (this module imports neither the scheduler nor the alerts). The state is two files in ``<BRAIN_HOME>/notify``:
``quiet.json`` (the manual quiet's end) and ``held.jsonl`` (one line per held notification: its text stays on this
machine, like the alerts state).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from . import paths, timing

STATE = "quiet.json"
HELD = "held.jsonl"
PASS = "critical"          # the level that is never held
DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(m|min|h|d)\s*$")
UNITS = {"m": 60, "min": 60, "h": 3600, "d": 86400}
HOURS = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*-\s*([01]?\d|2[0-3]):([0-5]\d)\s*$")
MAX_LINES = 25             # the summary names this many held notifications, then counts the rest
RANK = {"info": 0, "warn": 1, "error": 2, "critical": 3}


class QuietError(Exception):
    pass


def folder() -> Path:
    return paths.brain_home() / "notify"


def duration(text: str) -> timedelta:
    """2h, 90m, 1d; at most 7 days (a quiet with no end is a way to forget the alerts)."""
    m = DURATION.match(str(text))
    if not m or float(m.group(1)) <= 0:
        raise QuietError(f"{text!r}: a duration such as 90m, 2h or 1d")
    d = timedelta(seconds=float(m.group(1)) * UNITS[m.group(2)])
    if d > timedelta(days=7):
        raise QuietError(f"{text!r}: at most 7d")
    return d


def hours(text: str) -> tuple[int, int]:
    """'22:00-07:00' as minutes from midnight (start, end); the window may cross midnight."""
    m = HOURS.match(str(text))
    if not m or m.group(1, 2) == m.group(3, 4):
        raise QuietError(f"{text!r}: quiet_hours is HH:MM-HH:MM, local time (e.g. 22:00-07:00)")
    return int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))


def in_hours(text: str, now: datetime) -> bool:
    if not text:
        return False
    start, end = hours(text)
    t = now.astimezone()
    cur = t.hour * 60 + t.minute
    return start <= cur < end if start < end else (cur >= start or cur < end)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _at(text) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def manual_until(now: datetime | None = None) -> datetime | None:
    """The end of the manual quiet when it is running, else None."""
    now = now or datetime.now(timezone.utc)
    try:
        data = json.loads((folder() / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    until = _at(data.get("until")) if isinstance(data, dict) else None
    return until if until is not None and until > now else None


def start(span: timedelta, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    until = now + span
    folder().mkdir(parents=True, exist_ok=True)
    (folder() / STATE).write_text(json.dumps({"since": _iso(now), "until": _iso(until)}), encoding="utf-8")
    return until


def stop() -> bool:
    """End the manual quiet; True when one was recorded."""
    try:
        (folder() / STATE).unlink()
        return True
    except OSError:
        return False


def active(quiet_hours: str = "", now: datetime | None = None) -> str:
    """Why notifications below critical are held now ('' when they are not)."""
    now = now or datetime.now(timezone.utc)
    until = manual_until(now)
    if until is not None:
        return f"brain quiet, until {until.astimezone():%H:%M}"
    if in_hours(quiet_hours, now):
        return f"quiet hours {quiet_hours}"
    return ""


def holds(level: str, quiet_hours: str = "", now: datetime | None = None) -> bool:
    return level != PASS and bool(active(quiet_hours, now))


# --- the held notifications ---

def held() -> list[dict]:
    try:
        text = (folder() / HELD).read_text(encoding="utf-8")
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


def _write_held(rows: list[dict]) -> None:
    f = folder() / HELD
    if not rows:
        f.unlink(missing_ok=True)
        return
    tmp = f.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, f)


def hold(msg, now: datetime) -> None:
    """Keep ``msg`` (a notify.Message) for the summary."""
    folder().mkdir(parents=True, exist_ok=True)
    row = {"at": _iso(now), "project": msg.project, "level": msg.level, "source": msg.source, "key": msg.key,
           "title": msg.heading(), "body": msg.body.strip()[:600]}
    timing.append(folder() / HELD, row)   # under the folder's lock: notify.send may run in several sessions


def summary_text(rows: list[dict]) -> tuple[str, str]:
    """(level, body) of one project's held notifications: the highest level among them, then one line each (the latest
    of a key), the oldest first."""
    latest: dict[tuple, dict] = {}
    for r in rows:
        latest[(r.get("level"), r.get("key") or r.get("title"))] = r
    kept = sorted(latest.values(), key=lambda r: str(r.get("at")))
    level = max((r.get("level", "info") for r in kept), key=lambda x: RANK.get(x, 0), default="info")
    lines = [f"- {str(r.get('at', ''))[11:16]}Z {r.get('level')}: "
             f"{(str(r.get('body') or r.get('title')).splitlines() or [''])[0][:160]}" for r in kept[:MAX_LINES]]
    if len(kept) > MAX_LINES:
        lines.append(f"- and {len(kept) - MAX_LINES} more")
    return level, f"{len(rows)} held during the quiet:\n" + "\n".join(lines)


def release(registry: Mapping, *, now: datetime | None = None, dry_run: bool = False,
            env: Mapping[str, str] | None = None) -> list[str]:
    """Send the sum-up of what was held to each project whose quiet has ended; the lines to print. A summary that
    failed to send stays held for the next call. Called by ``brain quiet --off`` and by every alerts pass."""
    from . import notify   # here: notify imports this module
    now = now or datetime.now(timezone.utc)
    rows = held()
    if not rows:
        return []
    keep, lines = [], []
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(str(r.get("project")), []).append(r)
    for name, mine in by.items():
        project = registry.get(name)
        try:
            cfg = notify.config(project, registry) if project is not None else None
        except notify.NotifyError:
            cfg = None
        if cfg is None:
            lines.append(f"quiet: {name}: {len(mine)} held, project not in the registry (kept)")
            keep += mine
            continue
        if active(cfg.quiet_hours, now):
            keep += mine
            continue
        level, body = summary_text(mine)
        res = notify.send(cfg, notify.Message(name, level, body, f"{len(mine)} held during the quiet",
                                              source="quiet"), dry_run=dry_run, force=True, now=now, env=env,
                          queue=False)   # a summary that fails stays held: the next pass sends it again
        lines.append(f"quiet: {name}: summary of {len(mine)} held: {res.status}")
        if dry_run or res.status == "failed":
            keep += mine
    if not dry_run:
        _write_held(keep)
    return lines


def summary(projs=None, now: datetime | None = None) -> dict:
    """{until, hours: {project: window}, active, held}: what ``brain status`` and the cockpit show."""
    from . import notify, projects
    now = now or datetime.now(timezone.utc)
    if projs is None:
        try:
            projs = list(projects.load().values())
        except Exception:   # noqa: BLE001 (a registry error is not the quiet's to report)
            projs = []
    wins = {}
    for p in projs:
        try:
            q = notify.config(p).quiet_hours
        except notify.NotifyError:
            continue
        if q:
            wins[p.name] = q
    until = manual_until(now)
    return {"until": _iso(until) if until else "", "hours": wins,
            "active": bool(until) or any(in_hours(w, now) for w in wins.values()), "held": len(held())}


def line(s: dict) -> str:
    """The one line that says it ('' when nothing is quiet, declared or held)."""
    if not (s["until"] or s["hours"] or s["held"]):
        return ""
    parts = []
    if s["until"]:
        parts.append(f"quiet until {_at(s['until']).astimezone():%H:%M} (brain quiet --off ends it)")
    elif s["active"]:
        parts.append("quiet (declared hours)")
    else:
        parts.append("not quiet")
    if s["hours"]:
        parts.append("hours " + ", ".join(f"{k} {v}" for k, v in sorted(s["hours"].items())))
    parts.append(f"{s['held']} held" if s["held"] else "none held")
    return "; ".join(parts) + "; critical still goes through, no task paused"
