"""The wave quota gate (wi-brain-wave-quota-gate; RETRO-5 of the waves retro, 2026-11-03: a stream starts only while
the quota's forecast, its own estimate included, keeps the week under 90 % at its reset, and one master runs three
streams at most, their reviews included): two checks of the usage governor (brain.governor) on a start_session call,
and the count of the streams that fit now that brain brief, brain wave plan and brain usage guard print. Standard
library only, as the governor's hook.

It runs only with config.json ``usage.guard.wave_quota`` (:data:`DEFAULTS`; absent: off), and only for a start_session
call that starts a session now (:func:`starts_now`: ``initiation`` user_asked or none, or a ``proposal_id``; a
proposal card starts nothing):

  streams     deny when the calling session (the master) already has ``max_streams`` live streams: its children in
              the desktop app's session files (``spawnedFrom``, read through brain.sessions' closed list of keys),
              neither archived nor detached, that are *running* (their transcript written in the last
              ``live_minutes`` and its last turn not ended) or *starting* (created in the last 10 minutes, no
              transcript yet), plus the stream starts the governor let through (or asked the owner about) in the
              last :data:`UNSEEN` that no child of the master matches yet (``usage/starts.jsonl``, ``"stream":
              true``). A start is matched against every child of the master, archived and detached ones included,
              on its creation time first (the title or the app's short name only breaks a tie), before any child is
              judged live: a start that failed, or a child that finished and was archived within minutes, holds no
              slot.
  wave_quota  ask the owner when the week's forecast at its reset goes over ``ask_over_pct``: the week's percent as
              read (brain.governor.quota_now's reading or forecast, before its fresh_minutes cap), plus the last
              forecast's pace (``usage/quota.json``'s ``pace.pct_h``, only while that forecast is of the week in force)
              times the hours from that reading to the reset, plus this stream's cost in percent of the week: the
              brief's estimate (the ``usd=`` of its Cost estimate line), else the median session's (the forecast's
              ``live.median_session_usd``), converted by the forecast's ``pct_per_usd``.

Either check fails open: a forecast that cannot be read, a session the app does not know, a count past
:data:`BUDGET_S` (from before the app's sessions are read), or an error inside the gate let the call through with a
note in the hook's context. ``0`` turns either check off. :func:`room` gives the same reading as a count of the
streams that fit now.

Its cost in the hook: the app's session index (cached by brain.sessions), one pass over Claude Code's transcript
folders for the children's transcripts, and a tail of each child's transcript written in the last ``live_minutes``
(64 KB, once 1 MB when a last record is larger): ~40-70 ms measured with 204 app sessions and a master of 5 children.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import governor, paths

DEFAULTS = {"ask_over_pct": 90.0, "max_streams": 3}
BUDGET_S = 2.0   # the live streams' count gives up past this (the call goes through, with a note)
LIVE = ("running", "starting")   # what counts as a live stream (asking, idle, quiet, unknown do not)
UNSEEN = timedelta(minutes=1)    # a start no child matches counts this long (the app writes a child's file in seconds)
MATCH_SLACK_MS = 60_000          # a child created this long before a start's note still matches it (clock, write order)
TAIL = (65536, 1 << 20)          # a transcript's tail read for its turn: 64 KB, else once 1 MB (a large last record)
_USD_RE = re.compile(r"\busd=\$?(\d+(?:\.\d+)?)")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def config_of(value) -> tuple[dict | None, list[str]]:
    """usage.guard.wave_quota over :data:`DEFAULTS` (None: the gate is off), and what is wrong in it (a field of the
    wrong type is left at its default)."""
    if value is None:
        return None, []
    if not isinstance(value, dict):
        return None, [f"usage.guard.wave_quota: a mapping of {', '.join(DEFAULTS)} (the gate stays off)"]
    out, errors = dict(DEFAULTS), []
    ok = {"ask_over_pct": lambda v: _num(v) and 0 <= v <= 100, "max_streams": lambda v: _num(v) and isinstance(
        v, int) and v >= 0}
    want = {"ask_over_pct": "a number from 0 to 100", "max_streams": "a whole number of 0 or more"}
    for key, v in value.items():
        if key not in DEFAULTS:
            errors.append(f"usage.guard.wave_quota.{key}: unknown (known: {', '.join(DEFAULTS)})")
        elif ok[key](v):
            out[key] = float(v) if key == "ask_over_pct" else v
        else:
            errors.append(f"usage.guard.wave_quota.{key}: {want[key]}")
    return out, errors


def starts_now(inp: dict) -> bool:
    """Whether a start_session call starts a session now: the owner asked for it (``initiation`` user_asked, or none)
    or it starts a proposal (``proposal_id``); a proposal card (``offer``, ``own_initiative``) starts nothing
    (brain.budget counts a master's children the same way)."""
    return bool(inp.get("proposal_id")) or inp.get("initiation") in ("user_asked", None)


def estimate_usd(text: str) -> float | None:
    """The ``usd=N`` of a cost estimate's line (brain cost estimate, brain brief's « Cost estimate »), else None."""
    m = _USD_RE.search(str(text or ""))
    return float(m.group(1)) if m else None


# --- the forecast ---------------------------------------------------------------------------------------------------

def inputs(q: dict) -> dict:
    """What the projection reads from the last forecast (``usage/quota.json``): its pace (only while it is of the week
    in force: its reset the week reading's), its % per $ and the median session's cost; None for what is missing."""
    status = governor._read_json(paths.brain_home() / "usage" / "quota.json")
    status = status if isinstance(status, dict) else {}
    week, s_resets = q["windows"].get("week"), governor._dt(status.get("resets"))
    same = bool(week and status.get("window") == "week" and s_resets
                and abs(s_resets - governor._dt(week["resets"])) < timedelta(minutes=5))
    pct_h = _field(status, "pace", "pct_h", 0)
    ppu = _field(status, "conversion", "pct_per_usd")
    return {"pct_h": pct_h if same else None,
            "pct_per_usd": ppu or (1 / q["usd_per_pct"] if q.get("usd_per_pct") else None),
            "median_session_usd": _field(status, "live", "median_session_usd")}


def _field(status: dict, part: str, key: str, floor: float | None = None) -> float | None:
    """``status[part][key]`` as a float when it is a number above 0 (``floor`` 0: 0 or more), else None."""
    d = status.get(part) if isinstance(status.get(part), dict) else {}
    v = d.get(key)
    ok = _num(v) and (v >= floor if floor is not None else v > 0)
    return float(v) if ok else None


def projection(q: dict, now: datetime, inp: dict | None = None) -> dict | None:
    """The week's forecast at its reset: the percent as read (brain.governor.quota_now's reading or forecast, before
    its fresh_minutes cap: ``base_pct`` at ``at``) plus the last forecast's pace times the hours from that reading to
    the reset; ``now_pct`` the same at ``now``. None when a part is missing (no week reading in force, no pace of this
    week, no conversion)."""
    week, inp = q["windows"].get("week"), inp or inputs(q)
    if not week or inp["pct_h"] is None or not inp["pct_per_usd"]:
        return None
    base, at, resets = week.get("base_pct", week["pct"]), governor._dt(week["at"]), governor._dt(week["resets"])
    hours = max(0.0, (resets - at).total_seconds() / 3600)
    since = max(0.0, (now - at).total_seconds() / 3600)
    return {"read_pct": base, "at": week["at"], "hours": round(hours, 1), "pct_h": inp["pct_h"],
            "now_pct": round(min(base + inp["pct_h"] * since, 100.0), 1),
            "hours_left": round(max(0.0, (resets - now).total_seconds() / 3600), 1),
            "at_reset": round(base + inp["pct_h"] * hours, 1), "resets": week["resets"],
            "pct_per_usd": inp["pct_per_usd"]}


def stream_usd(inp: dict, median: float | None) -> tuple[float | None, str]:
    """(the cost of the stream a start_session call starts, where it comes from): the brief's estimate (its
    ``usd=``), else the median session's of the last forecast, else (None, 'no estimate')."""
    usd = estimate_usd("\n".join(str(inp.get(k) or "") for k in ("prompt", "background", "title")))
    if usd is not None:
        return usd, "the brief's estimate"
    if median:
        return median, "the median session's cost, the brief giving no estimate"
    return None, "no estimate"


# --- the live streams -----------------------------------------------------------------------------------------------

def turn(records: list[dict]) -> str:
    """Where a transcript's turn is from its last records: ``asking``, ``idle`` or ``active``; brain.cockpit.turn's
    reading (a stop hook's summary ends a turn), kept here because the cockpit's import costs a second in a hook."""
    for r in reversed(records):
        kind = r.get("type")
        if kind == "system" and r.get("subtype") == "stop_hook_summary":
            return "idle"
        if kind == "user":
            return "active"
        if kind != "assistant":
            continue   # a compaction boundary, a notice, the app's own records: look further back
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        content = msg.get("content") if isinstance(msg.get("content"), list) else []
        uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        if any(b.get("name") == "AskUserQuestion" for b in uses):
            return "asking"
        return "idle" if not uses and msg.get("stop_reason") == "end_turn" else "active"
    return "active"


def _transcripts(sids: set[str], deadline: float = float("inf")) -> dict[str, Path] | None:
    """{session: its newest main transcript} for ``sids``, in one pass over Claude Code's transcript folders (each
    folder listed once, whatever the number of children); None past ``deadline`` (time.monotonic)."""
    want = {f"{s}.jsonl": s for s in sids if s}
    out: dict[str, Path] = {}
    newest: dict[str, int] = {}
    try:
        folders = [d.path for d in os.scandir(paths.projects_dir()) if d.is_dir()] if want else []
    except OSError:
        return out
    for folder in folders:
        if time.monotonic() > deadline:
            return None
        try:
            with os.scandir(folder) as entries:
                hits = [(want[e.name], e) for e in entries if e.name in want]
        except OSError:
            continue
        for sid, e in hits:
            m = e.stat().st_mtime_ns
            if m > newest.get(sid, -1):
                newest[sid], out[sid] = m, Path(e.path)
    return out


def _records(f: Path, size: int) -> list[dict]:
    out = []
    for line in governor._tail_lines(f, size):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def child_state(node: dict, now: datetime, lim: dict, found: dict[str, Path] | None = None) -> str:
    """A child's state for the streams cap: ``starting`` (created in the last 10 minutes, no transcript or no record
    in it yet), ``running`` (its transcript written in the last ``live_minutes`` and its turn not ended), else
    ``asking``, ``idle``, ``quiet`` (no write for ``live_minutes``) or ``unknown`` (no transcript, or no whole record
    in its last 1 MB, and not new). ``found``: the transcripts :func:`_transcripts` found, else looked up here."""
    created = node.get("created")
    young = _num(created) and created >= governor._ms(now - governor.PENDING)
    sid = str(node.get("session") or "")
    f = (found if found is not None else _transcripts({sid}) or {}).get(sid) if sid else None
    st = governor._stat(f) if f else None
    if st is None:
        return "starting" if young else "unknown"
    if now.timestamp() - st[0] / 1e9 > lim["live_minutes"] * 60:
        return "quiet"
    records = _records(f, TAIL[0]) or _records(f, TAIL[1])   # a last record past 64 KB: once more, larger
    if not records:
        return "starting" if young else "unknown"
    t = turn(records)
    return "running" if t == "active" else t


def _stream_starts(now: datetime, by: str) -> list[dict]:
    """The stream starts the governor noted for session ``by`` in the last :data:`UNSEEN`, the oldest first."""
    out = []
    for line in governor._tail_log(paths.brain_home() / "usage" / "starts.jsonl", 16384):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        at = governor._dt(r.get("at")) if isinstance(r, dict) else None
        if at and now - UNSEEN <= at <= now + timedelta(minutes=1) and r.get("stream") and r.get("by") == by:
            out.append(dict(r, at_ms=governor._ms(at)))
    return sorted(out, key=lambda r: r["at_ms"])


def _master(idx: dict, master: str) -> str:
    """The app's id of ``master`` (its app id or its transcript's), '' when the app does not know it."""
    if master in idx:
        return master
    return next((h for h, m in idx.items() if master and m.get("session") == master), "")


def _same(r: dict, m: dict) -> bool:
    """A noted start and a child that carry the same title, or the same short name (start_session's ``name``)."""
    return bool(r.get("title") and r["title"] == m.get("title") or r.get("name") and r["name"] == m.get("name"))


def _unmatched(starts: list[dict], family: list[dict]) -> list[str]:
    """The noted starts no child of the master matches (every child: archived and detached ones too, so a start
    whose child already finished is matched): each start, the oldest first, takes the child created closest after it
    (within :data:`MATCH_SLACK_MS` before it), the title or short name breaking a tie of creation times (5 s
    apart or less); each child matches one start at most. Their titles."""
    left, out = [m for m in family if _num(m.get("created"))], []
    for r in starts:
        cands = [m for m in left if m["created"] >= r["at_ms"] - MATCH_SLACK_MS]
        if not cands:
            out.append(str(r.get("title") or "a proposal started"))
            continue
        left.remove(min(cands, key=lambda m: (abs(m["created"] - r["at_ms"]) // 5000, not _same(r, m),
                                              abs(m["created"] - r["at_ms"]))))
    return out


def _family(idx: dict, host: str) -> tuple[list[dict], list[dict]]:
    """Every child of ``host`` (archived and detached ones too: the starts are matched against them), and those
    neither archived nor detached, the newest first (the ones that may be live)."""
    family = [m for m in idx.values() if m.get("parent") == host]
    kids = sorted((m for m in family if not m.get("archived") and m.get("detached") is not True),
                  key=lambda m: -(m.get("created") or 0))
    return family, kids


def _running(kids: list[dict], now: datetime, lim: dict, deadline: float) -> list[str] | None:
    """The names of the children that run or start (:data:`LIVE`), their transcripts found in one pass; None past
    ``deadline`` (time.monotonic)."""
    found = _transcripts({str(m.get("session") or "") for m in kids}, deadline)
    if found is None:
        return None
    names = []
    for m in kids:
        if time.monotonic() > deadline:
            return None
        if child_state(m, now, lim, found) in LIVE:
            names.append(str(m.get("name") or m.get("title") or m.get("host_id")))
    return names


def _not_counted(note: str) -> dict:
    return {"n": None, "names": [], "note": note}


def live_streams(master: str, now: datetime, lim: dict, budget_s: float | None = None) -> dict:
    """The live streams of ``master`` (its app id or its transcript's): {n, names, host_id, note}; ``n`` is None, with
    the reason in ``note``, when they cannot be counted (no app on the machine, a session the app does not know, a
    count past ``budget_s``, timed from before the app's sessions are read)."""
    from . import sessions  # ~35 ms, only for a start the gate checks
    budget_s = BUDGET_S if budget_s is None else budget_s
    deadline, late = time.monotonic() + budget_s, f"the live streams were not counted within {budget_s:g} s"
    idx = sessions.app_index()
    if time.monotonic() > deadline:
        return _not_counted(late)
    host = _master(idx, master) if idx is not None else ""
    if not host:
        return _not_counted("the desktop app's sessions are not on this machine" if idx is None
                            else "this session is not one of the desktop app's")
    family, kids = _family(idx, host)
    names = _running(kids, now, lim, deadline)
    if names is None:
        return _not_counted(late)
    names += _unmatched(_stream_starts(now, str(idx[host].get("session") or master)), family)
    return {"n": len(names), "names": names, "host_id": host, "note": ""}


# --- the gate -------------------------------------------------------------------------------------------------------

def state(wq: dict, inp: dict, master: str, now: datetime, lim: dict, q: dict) -> dict:
    """What the gate sees for one start: the forecast at the reset, this stream's cost, the master's live streams and
    the notes of what could not be read (it fails open)."""
    out: dict = {**wq, "projection": None, "usd": None, "usd_basis": "", "item_pct": None, "median_usd": None,
                 "streams": {"n": None}, "notes": []}
    try:
        if wq["ask_over_pct"]:
            got = inputs(q)
            out["median_usd"] = got["median_session_usd"]
            p = out["projection"] = projection(q, now, got)
            out["usd"], out["usd_basis"] = stream_usd(inp, got["median_session_usd"])
            if p is None:
                out["notes"].append("the week's forecast cannot be read (no week reading in force, or no pace of this "
                                    "week or conversion in usage/quota.json: brain usage quota)")
            elif out["usd"] is not None:
                out["item_pct"] = round(out["usd"] * p["pct_per_usd"], 2)
        if wq["max_streams"]:
            out["streams"] = live_streams(master, now, lim)
            if out["streams"]["n"] is None:
                out["notes"].append(f"the live streams are not counted: {out['streams']['note']}")
    except Exception as exc:   # noqa: BLE001 - the gate fails open, said in the note
        out["notes"].append(f"the gate failed ({type(exc).__name__}: {str(exc)[:80]})")
    return out


def for_start(kind: str, lim: dict, inp: dict, master: str, now: datetime, q: dict) -> dict | None:
    """The gate's state for a governor call (:func:`state`), None when it does not apply: the gate off, not a
    start_session, or a call that starts nothing now."""
    wq = lim.get("wave_quota")
    if kind != "session" or not lim["enabled"] or not wq or not starts_now(inp):
        return None
    return state(wq, inp, master, now, lim, q)


def verdict(w: dict | None) -> tuple[str, str, str] | None:
    """The gate's answer: the first of :func:`verdicts`; None to let it through (and when the gate is off or could not
    read what it needs)."""
    return next(verdicts(w), None)


def verdicts(w: dict | None):
    """Each of the gate's checks that holds, as (decision, check, reason), in order: deny a stream past max_streams,
    then ask past ask_over_pct at the reset. The governor asks for them one at a time (brain.governor._session_caps),
    so an override that lifts ``streams`` lets ``wave_quota`` decide."""
    if not w:
        return
    ss = w["streams"]
    if w["max_streams"] and ss.get("n") is not None and ss["n"] >= w["max_streams"]:
        names = ", ".join(ss["names"][:4])
        yield ("deny", "streams", f"a new stream refused: this session already has {ss['n']} live stream(s) "
               f"({names or 'not named'}), the cap is {w['max_streams']} (usage.guard.wave_quota.max_streams: "
               "the streams of one master, their reviews included); wait until one has reported and is archived")
    p, pct = w["projection"], w["item_pct"]
    if not w["ask_over_pct"] or p is None or p["at_reset"] + (pct or 0.0) <= w["ask_over_pct"]:
        return
    cost = (f" plus this stream's {pct:.1f} % (${w['usd']:.2f}, {w['usd_basis']})" if pct is not None
            else f" ({w['usd_basis']} for this stream)")
    yield ("ask", "wave_quota", f"a new stream: the week's forecast at its reset "
            f"{p['resets'][:16].replace('T', ' ')} UTC is {p['at_reset']:.0f} % ({p['read_pct']:.0f} % at "
            f"{p['at'][11:16]} UTC + {p['pct_h']:.2f} %/h x {p['hours']:.1f} h){cost}: "
            f"{p['at_reset'] + (pct or 0.0):.0f} %, over "
            f"{w['ask_over_pct']:g} % (usage.guard.wave_quota.ask_over_pct); start it anyway?")


def notes(w: dict | None) -> list[str]:
    """The hook context's lines for a start the gate let through unchecked (what it could not read)."""
    return [f"Wave quota gate (usage.guard.wave_quota): {n}; the start goes through unchecked by it."
            for n in (w or {}).get("notes") or []]


# --- how many fit now -----------------------------------------------------------------------------------------------

def _fit(at_reset: float | None, pcts: list[float | None], ask: float) -> int | None:
    """How many of the streams costing ``pcts`` (% of the week, in order) fit before the forecast at the reset goes
    over ``ask``; None when the forecast or the first cost is unknown."""
    if at_reset is None or not pcts or pcts[0] is None:
        return None
    n, total = 0, at_reset
    for p in pcts:
        if p is None or total + p > ask:
            break
        total += p
        n += 1
    return n


def _counts(w: dict, usds: list[float | None]) -> dict:
    """by_quota, by_streams and fit (the smaller of the known ones) of the gate's state ``w``, each stream at
    ``usds`` (None: the median session's)."""
    p, n = w["projection"], w["streams"].get("n")
    costs = [u if u is not None else w["median_usd"] for u in usds]
    pcts = [None if p is None or c is None else round(c * p["pct_per_usd"], 2) for c in costs]   # as item_pct
    by_quota = _fit(p and p["at_reset"], pcts, w["ask_over_pct"]) if w["ask_over_pct"] else None
    by_streams = max(0, w["max_streams"] - n) if w["max_streams"] and n is not None else None
    known = [x for x in (by_quota, by_streams) if x is not None]
    return {"by_quota": by_quota, "by_streams": by_streams, "fit": min(known) if known else None, "pcts": pcts}


def room(cwd: str, master: str, usds: list[float | None], now: datetime | None = None) -> dict | None:
    """How many streams fit now (brain brief, brain wave plan, brain usage guard): the streams left to ``master``
    (max_streams less its live ones) and those whose costs ``usds`` (in order; None: the median session's) fit under
    ask_over_pct at the reset; ``fit`` the smaller of the two known ones, ``line`` in words. None while
    usage.guard.wave_quota is off."""
    now = now or governor._now()
    lim = governor.settings(cwd)["limits"]
    wq = lim.get("wave_quota")
    if not lim["enabled"] or not wq:
        return None
    w = state(wq, {}, master, now, lim, governor.quota_now(now, lim))
    w.update(_counts(w, usds))
    w["line"] = line(w)
    return w


def _quota_part(w: dict) -> str:
    p = w["projection"]
    if p is None:
        return "by the quota: not known (brain usage quota)"
    cost = next((x for x in w.get("pcts") or [] if x is not None), None)
    return (f"by the quota {w['by_quota'] if w['by_quota'] is not None else '?'}: the week {p['now_pct']:.0f} % now, "
            f"{p['at_reset']:.0f} % at its reset {p['resets'][:16].replace('T', ' ')} UTC at the last forecast's "
            f"pace, asked over {w['ask_over_pct']:g} %" + (f", a stream {cost:.1f} %" if cost is not None else ""))


def _streams_part(w: dict) -> str:
    s = w["streams"]
    if s.get("n") is None:
        return f"by the streams: not known ({s.get('note') or 'no master session'})"
    return (f"by the streams {w['by_streams']}: {s['n']} live of {w['max_streams']}"
            + (f" ({', '.join(s['names'][:4])})" if s.get("names") else ""))


def line(w: dict) -> str:
    """One line of :func:`room`: the streams that fit now and why."""
    parts = ([_quota_part(w)] if w["ask_over_pct"] else []) + ([_streams_part(w)] if w["max_streams"] else [])
    fit = w.get("fit")
    return f"{fit if fit is not None else 'not known'} ({'; '.join(parts)}; usage.guard.wave_quota)"


def guard_line(lim: dict, w: dict | None) -> str:
    """brain usage guard's ``waves`` line."""
    wq = lim.get("wave_quota")
    if not wq:
        return "  waves     off (usage.guard.wave_quota not set)"
    if not w:
        return "  waves     off (the governor off)"
    return (f"  waves     ask over {wq['ask_over_pct']:g} % at the reset, {wq['max_streams']} stream(s) at most a "
            f"master; fit now {w['line']}")
