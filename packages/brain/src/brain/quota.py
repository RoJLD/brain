"""Quota pacing (wi-brain-quota-pacing; spec-brain-cost §3.3; COST-3, 2026-11-02: the plan's quota from the
readings the sessions note, converted by the token ledger), at zero token.

The plan's quota is the real limit: a weekly window that resets at a fixed time (Monday 12:00 UTC on 2026-11-02) and,
at times, a 5-hour one. Only a model reads it, in the app (``get_usage``: each window's percent used and reset time).
A session that read it notes it with its time::

  brain usage quota --observe 28 --resets 2026-11-09T12:00Z [--window week|5h] [--at WHEN]

which appends the reading to ``<BRAIN_HOME>/usage/quota.jsonl`` (time, window, percent, reset, plan, host); without
``--resets`` a weekly reading takes the last reading's reset, moved by whole weeks past ``--at``. The token ledger
(brain.usage) has every session's cost at API prices by UTC hour; from them:

  conversion  each reading's percent over the ledger's cost since its window started (its reset minus the window's
              length): the percent of the window per dollar at API prices, the median of the readings of the last
              ``FACTOR_DAYS`` days (each with ``MIN_USD`` of cost at least); 100 / it: the window at API prices.
              Only the readings of the plan in force count (a reading's own ``plan``, else the plan of its day in
              config.json ``usage.plans``): a plan's quota in dollars is its own, so a median across an Ultra and
              a Pro week would be neither. Until the plan has ``CAL_MIN`` converted readings the conversion is
              uncalibrated and the weekly window is not converted; the 5-hour window's latest reading, with the
              ledger's cost since, gives an estimate of that window instead.
  now         the latest reading of the window in force plus the ledger's cost since, converted; without one, the
              cost since the window started, converted (an estimate, said so).
  pace        the cost of the last ``PACE_HOURS`` hours per hour, converted: the percent at the reset if it goes on,
              and the time it reaches 100 % when that comes first.
  session-h   what a session-hour cost over the last ``SESSION_HOUR_DAYS`` days: the sessions' hourly buckets (each
              with its subagents' and workflow agents' cost) over their count; the usage governor's cap reads it when
              it is above config.json ``usage.guard.session_hour_usd``, so an ultracode wave's cost counts.
  live        the sessions whose ledger row moved in the last ``LIVE_MIN`` minutes, their cost of the last hour, and
              what their items have left: each item's recorded estimate (props.cost_estimate), else the estimate of
              the most alike finished items times the class's calibration (brain.cost), minus its cost so far; a
              session that serves no item: the median session's cost minus its own.
  queue       the startable P0/P1 items no live session serves, in priority order, each at its estimate: how many
              fit in the room the live sessions leave.
  advice      under ``WARN`` % at the reset: room for waves (and how many queue items fit); from ``WARN`` to 100 %:
              open only P0/P1 waves; 100 % before the reset, at the pace or with the live sessions' left: open no new
              wave, finish the live ones.

``brain usage quota`` prints it, ``brain status`` gives its line, and each computation writes
``<BRAIN_HOME>/usage/quota.json`` (the forecast and its line): the cockpit's to read, as its panels re-read a file
that changed.

Known limits: the ledger is this machine's, while sessions on another machine spend the same quota: the conversion
overstates the percent per dollar while they run. The per-model weekly windows (Fable) are not converted: the hourly
buckets are not split by model.
"""

from __future__ import annotations

import json
import os
import re
import socket
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, cost, paths, projects, resume, usage

WINDOWS = {"week": timedelta(days=7), "5h": timedelta(hours=5)}
FACTOR_DAYS = 28
MIN_USD = 5.0  # a reading over less cost since its window started gives no conversion
CAL_MIN = 3  # converted readings of the plan in force before its conversion counts as calibrated
PACE_HOURS = 24
LIVE_MIN = 15
SKEW = timedelta(minutes=5)  # a reading this far after now is a clock's skew, not the future; two resets this close
# are the same (get_usage gives 2026-11-09T12:00:00.433Z, then 11:59:59.654Z)
WARN = 85.0
SESSION_HOUR_DAYS = 7
SESSION_HOUR_MIN = 4  # session-hours before the measure is given
SESSION_HOUR_MIN_USD = 0.5  # a session's hour under this (a resume, a last message) is not a session-hour
LEVELS = ("unknown", "room", "p0p1", "none")
_Z_RE = re.compile(r"Z$", re.I)


class QuotaError(ValueError):
    pass


def readings_file() -> Path:
    return paths.brain_home() / "usage" / "quota.jsonl"


def status_file() -> Path:
    return paths.brain_home() / "usage" / "quota.json"


def parse_time(text: str | None, now: datetime) -> datetime:
    """An ISO 8601 time (``2026-11-09T12:00Z``, ``2026-11-09T12:00:00.433Z``, ``2026-11-02 21:05``; UTC when it names
    no zone) or ``now``."""
    t = (text or "").strip()
    if not t or t.lower() == "now":
        return now
    try:
        dt = datetime.fromisoformat(_Z_RE.sub("+00:00", t.replace(" ", "T", 1)))
    except ValueError:
        raise QuotaError(f"{text!r}: an ISO time (2026-11-09T12:00Z) or now") from None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _dt(text: str | None) -> datetime | None:
    try:
        return parse_time(text, datetime.now(timezone.utc)) if text else None
    except QuotaError:
        return None


def when(dt: datetime | None) -> str:
    """``Mon 2026-11-09 12:00 UTC``."""
    return dt.astimezone(timezone.utc).strftime("%a %Y-%m-%d %H:%M UTC") if dt else "-"


# --- readings ---

def load_readings() -> list[dict]:
    """The readings noted on this machine, oldest first; a line that is not a reading is skipped."""
    out = []
    try:
        lines = readings_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("window") in WINDOWS and _dt(r.get("at")) and isinstance(
                r.get("pct"), (int, float)):
            out.append(r)
    return sorted(out, key=lambda r: r["at"])


def infer_resets(readings: list[dict], window: str, at: datetime) -> datetime | None:
    """The reset in force at ``at``: the last reading's, moved by whole windows past ``at`` (a weekly window resets at
    a fixed time; a 5-hour one starts with its first message, so it is never inferred)."""
    if window != "week":
        return None
    last = next((_dt(r.get("resets")) for r in reversed(readings) if r["window"] == window and r.get("resets")), None)
    if last is None:
        return None
    step = WINDOWS[window]
    while last <= at:
        last += step
    while last - step > at:
        last -= step
    return last


def observe(pct: float, window: str = "week", at: datetime | None = None, resets: datetime | None = None,
            plans=None) -> dict:
    """Append a reading of the plan's quota (``get_usage``'s percent used of ``window``, read at ``at``) and return
    it."""
    now = usage.now_utc()
    at = at or now
    if window not in WINDOWS:
        raise QuotaError(f"{window!r}: one of {', '.join(WINDOWS)}")
    if not 0 <= pct <= 100:
        raise QuotaError(f"{pct}: a percent between 0 and 100")
    if at > now + SKEW:
        raise QuotaError(f"{iso(at)}: a reading in the future")
    resets = resets or infer_resets(load_readings(), window, at)
    if resets is not None:
        resets = (resets + timedelta(seconds=30)).replace(second=0, microsecond=0)  # to the nearest minute
    if resets is None:
        raise QuotaError(f"no reset known for the {window} window: give --resets (get_usage's resetsAt)")
    if not at < resets <= at + WINDOWS[window]:
        raise QuotaError(f"{iso(resets)}: the {window} window in force at {iso(at)} resets after it and within "
                         f"{WINDOWS[window]}")
    rec = {"v": 1, "at": iso(at), "window": window, "pct": float(pct), "resets": iso(resets),
           "plan": usage.plan_of(iso(at)[:10], plans), "host": socket.gethostname()}
    f = readings_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# --- conversion ---

def plan_of_reading(r: dict, plans=None) -> str:
    """The plan a reading was taken under: its own ``plan``, else the plan of its day in ``plans``."""
    return str(r.get("plan") or "") or usage.plan_of(str(r.get("at") or "")[:10], plans)


def calibrate(rows: list[dict], readings: list[dict], window: str, now: datetime, plan: str | None = None,
              plans=None) -> dict | None:
    """{pct_per_usd, usd_per_pct, quota_usd, n, plan, readings: [...]}: the readings of ``plan`` (every plan when
    None) in the last ``FACTOR_DAYS`` days with ``MIN_USD`` of cost since their window started, each its percent
    over that cost, and their median; None without one. Whether ``n`` is enough is the caller's (``CAL_MIN``)."""
    out = []
    for r in readings:
        at, resets = _dt(r.get("at")), _dt(r.get("resets"))
        if r["window"] != window or not at or not resets or at < now - timedelta(days=FACTOR_DAYS):
            continue
        if plan and plan_of_reading(r, plans) != plan:
            continue
        spent = usage.cost_between(rows, resets - WINDOWS[window], at)
        if spent >= MIN_USD and r["pct"] > 0:
            out.append({**r, "usd": round(spent, 2), "pct_per_usd": r["pct"] / spent})
    if not out:
        return None
    f = statistics.median(x["pct_per_usd"] for x in out)
    return {"pct_per_usd": f, "usd_per_pct": 1 / f, "quota_usd": 100 / f, "n": len(out), "plan": plan or "",
            "readings": out}


def estimate_5h(rows: list[dict], readings: list[dict], now: datetime, plan: str | None = None,
                plans=None) -> dict | None:
    """The 5-hour window in force estimated from its latest reading of ``plan``: the reading's percent plus the
    ledger's cost since, at the percent per dollar that reading itself gave (its percent over the cost since the
    window started; without ``MIN_USD`` of it, the reading alone). None without a reading in force."""
    span = WINDOWS["5h"]
    best = None
    for r in readings:
        at, resets = _dt(r.get("at")), _dt(r.get("resets"))
        if r["window"] != "5h" or not at or not resets or not now < resets <= now + span + SKEW or at > now + SKEW:
            continue
        if plan and plan_of_reading(r, plans) != plan:
            continue
        if best is None or r["at"] > best[0]["at"]:
            best = (r, at, resets)
    if best is None:
        return None
    r, at, resets = best
    spent = usage.cost_between(rows, resets - span, at)
    since = usage.cost_between(rows, min(at, now), now)
    f = r["pct"] / spent if spent >= MIN_USD and r["pct"] > 0 else None
    return {"pct_now": round(min(100.0, r["pct"] + (since * f if f else 0.0)), 1), "read_pct": r["pct"],
            "at": r["at"], "resets": iso(resets), "since_usd": round(since, 2), "converted": f is not None}


# --- the estimates of items ---

def estimator(led: cost.Ledger):
    """item id -> (usd, basis) or None: its recorded estimate, else the most alike finished items' median times the
    class's calibration (brain.cost)."""
    pool = cost.history(led)
    cal = cost.calibration(cost.backtests(led))

    def est(item_id: str):
        it = led.items.get(item_id)
        if it is None:
            return None
        rec = cost.parse_estimate(str(it.props.get("cost_estimate") or "")).get("usd")
        if rec:
            return rec, "recorded"
        target = cost.target_of(led, item_id)
        raw = cost.raw_estimate([a for a in pool if a["id"] != item_id], target)
        if not raw["cost"]:
            return None
        c = cal.get(target["class"]) or cal.get("*") or {"factor": 1.0}
        return raw["cost"]["median"] * c["factor"], "similar"

    return est


def live_of(led: cost.Ledger, now: datetime, est) -> dict:
    """The live sessions (a row that moved in the last ``LIVE_MIN`` minutes), their cost of the last hour and what
    their items have left."""
    live = [r for r in led.rows if (_dt(r.get("end")) or now - timedelta(days=1)) >= now - timedelta(minutes=LIVE_MIN)]
    week = [r.get("cost") or 0.0 for r in led.rows if r not in live and usage.in_window(
        r, str((now - timedelta(days=7)).date()), "")]
    median = statistics.median(week) if week else 0.0
    left, items = 0.0, []
    for r in live:
        served = [i for i in r.get("served") or [] if i in led.items]
        known = [(i, est(i)) for i in served]
        known = [(i, e) for i, e in known if e]
        if known:
            for i, (usd, _basis) in known:
                if i not in items:
                    items.append(i)
                    left += max(0.0, usd - cost.actual(led.items[i])["cost"])
        else:
            left += max(0.0, median - (r.get("cost") or 0.0))
    return {"sessions": len(live), "items": items, "last_hour_usd": round(usage.cost_between(
        led.rows, now - timedelta(hours=1), now), 2), "left_usd": round(left, 2), "median_session_usd": round(median, 2)}


def queue_of(led: cost.Ledger, projs: list[projects.Project], skip: list[str], est) -> list[dict]:
    """The startable P0/P1 items (brain.status's frontier) not in ``skip``, P0 first, each with its estimate."""
    from .status import _store, frontier  # brain.status imports this module

    out = []
    for p in projs:
        if not p.root.is_dir():
            continue
        for n in frontier(_store(p)):
            pr = resume._priority(n)
            if pr not in resume.PRIORITIES or n["id"] in skip:
                continue
            e = est(n["id"])
            out.append({"id": n["id"], "project": p.name, "priority": pr, "usd": round(e[0], 2) if e else None,
                        "basis": e[1] if e else ""})
    return sorted(out, key=lambda q: (q["priority"], q["project"], q["id"]))


# --- the session-hour ---

def session_hour(rows: list[dict], now: datetime, days: int = SESSION_HOUR_DAYS) -> dict | None:
    """What a session-hour cost at API prices over the last ``days`` days (wi-brain-usage-workflow-agents): the cost
    of the sessions' hourly buckets over their count, a bucket being one session's UTC hour with
    ``SESSION_HOUR_MIN_USD`` of cost at least. A session's hours hold its subagents' and workflow agents' cost (brain.usage merges them), so an
    hour that ran a workflow costs its agents too. None below ``SESSION_HOUR_MIN`` buckets. The governor reads it
    (``quota.json``) when it is above config.json ``usage.guard.session_hour_usd``."""
    lo = now - timedelta(days=days)
    usd, n = 0.0, 0
    for r in rows:
        for key, b in (r.get("hours") or {}).items():
            c = b.get("cost") or 0.0
            try:
                at = datetime.fromisoformat(key + ":00:00").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if lo <= at < now and c >= SESSION_HOUR_MIN_USD:
                usd += c
                n += 1
    if n < SESSION_HOUR_MIN:
        return None
    return {"usd": round(usd / n, 2), "hours": n, "total_usd": round(usd, 2), "days": days}


# --- the forecast ---

def forecast(rows: list[dict], readings: list[dict], now: datetime, window: str = "week", live: dict | None = None,
             queue: list[dict] | None = None, plans=None) -> dict:
    """The window's percent now, at the reset at the last ``PACE_HOURS`` hours' pace, the live sessions' and the
    queue's share, and the advice (``LEVELS``). Only the readings of the plan in force (``plans``: config.json
    ``usage.plans``) are used; below ``CAL_MIN`` converted ones the conversion is uncalibrated (``uncalibrated``)
    and a weekly forecast gives the 5-hour window's estimate (``window_5h``) instead."""
    plan = usage.plan_of(iso(now)[:10], plans)
    every = readings  # the weekly reset is the account's, whatever the plan: only the conversion is the plan's
    readings = [r for r in readings if not plan or plan_of_reading(r, plans) == plan]
    fc: dict = {"window": window, "now": iso(now), "plan": plan, "readings": len(
        [r for r in readings if r["window"] == window])}
    cal = calibrate(rows, readings, window, now, plan, plans)
    n_cal = cal["n"] if cal else 0
    if n_cal < CAL_MIN:
        cal = None
    fc["uncalibrated"] = None if cal else {"plan": plan, "n": n_cal, "needed": CAL_MIN}
    if fc["uncalibrated"] and window == "week":
        fc["window_5h"] = estimate_5h(rows, readings, now, plan, plans)
    fc["conversion"] = cal and {k: (round(v, 6) if isinstance(v, float) else v) for k, v in cal.items()
                                if k != "readings"} | {"readings": [
                                    {k: r[k] for k in ("at", "pct", "resets", "usd", "host") if k in r}
                                    | {"pct_per_usd": round(r["pct_per_usd"], 6)} for r in cal["readings"]]}
    f = cal["pct_per_usd"] if cal else None
    resets = infer_resets(every, window, now) if window == "week" else next(
        (_dt(r["resets"]) for r in reversed(every) if r["window"] == window and (_dt(r.get("resets")) or now) > now),
        None)
    current = [r for r in readings if r["window"] == window and resets
               and abs((_dt(r.get("resets")) or now) - resets) <= SKEW
               and (_dt(r["at"]) or now) <= now + SKEW]
    fc["resets"], fc["hours_left"] = iso(resets), round((resets - now).total_seconds() / 3600, 1) if resets else None
    pct = None
    if current:
        r = max(current, key=lambda x: x["at"])
        since = usage.cost_between(rows, min(_dt(r["at"]), now), now)
        pct = r["pct"] + (since * f if f else 0.0)
        fc["reading"] = {"at": r["at"], "pct": r["pct"], "since_usd": round(since, 2)}
        fc["estimated"] = False
    elif resets and f:
        spent = usage.cost_between(rows, resets - WINDOWS[window], now)
        pct = spent * f
        fc["reading"] = None
        fc["estimated"] = True
    fc["pct_now"] = round(pct, 1) if pct is not None else None
    if f:
        usd = usage.cost_between(rows, now - timedelta(hours=PACE_HOURS), now)
        pace = {"hours": PACE_HOURS, "usd": round(usd, 2), "usd_h": round(usd / PACE_HOURS, 2),
                "pct_h": round(usd / PACE_HOURS * f, 3)}
        if pct is not None and resets:
            at_reset = pct + pace["pct_h"] * (resets - now).total_seconds() / 3600
            pace["at_reset"] = round(at_reset, 1)
            if at_reset >= 100 and pace["pct_h"] > 0:
                full = now + timedelta(hours=max(0.0, 100 - pct) / pace["pct_h"])
                pace["full_at"] = iso(full) if full < resets else None
        fc["pace"] = pace
    fc["session_hour"] = session_hour(rows, now)
    if live is not None:
        fc["live"] = dict(live, left_pct=round(live["left_usd"] * f, 1) if f else None)
    if queue is not None:
        q = {"items": len(queue), "usd": round(sum(x["usd"] or 0 for x in queue), 2), "fit": 0, "fit_usd": 0.0,
             "first": [x["id"] for x in queue[:5]]}
        if f and pct is not None:
            room = 100 - pct - ((live or {}).get("left_usd") or 0) * f
            q["room_pct"] = round(room, 1)
            used = 0.0
            for x in queue:
                if x["usd"] is None or used + x["usd"] * f > room:
                    break
                used += x["usd"] * f
                q["fit"] += 1
                q["fit_usd"] += x["usd"]
            q["fit_usd"] = round(q["fit_usd"], 2)
        fc["queue"] = q
    fc["level"], fc["advice"] = advice(fc)
    fc["line"] = line(fc)
    return fc


def advice(fc: dict) -> tuple[str, str]:
    pace, pct = fc.get("pace") or {}, fc.get("pct_now")
    un = fc.get("uncalibrated")
    if un and "at_reset" not in pace:
        w5 = fc.get("window_5h")
        est = (f"; the 5h window is about {w5['pct_now']:.0f} % (estimated from its {w5['read_pct']:.0f} % reading)"
               if w5 else "; read get_usage, then brain usage quota --observe N --resets T")
        return "unknown", (f"uncalibrated: {un['plan'] or 'this plan'} has {un['n']} of {un['needed']} converted "
                           f"readings, the {fc['window']} window is not converted (a reading needs "
                           f"${MIN_USD:g} of ledger cost since its window started to convert){est}")
    if pct is None or "at_reset" not in pace:
        return "unknown", ("read get_usage, then brain usage quota --observe N --resets T" if not fc["readings"]
                           else "a reading needs $%g of ledger cost since its window started to convert" % MIN_USD
                           if not fc.get("conversion") else "no reading in this window: note one")
    live_full = pct + ((fc.get("live") or {}).get("left_pct") or 0) >= 100
    if pace["at_reset"] >= 100 or live_full:
        return "none", "open no new wave, finish the live ones"
    if pace["at_reset"] >= WARN:
        return "p0p1", "open only P0/P1 waves"
    q = fc.get("queue")
    return "room", ("room for waves" + (f": about {q['fit']} of the {q['items']} startable P0/P1 item(s) fit"
                                        if q and q["items"] else ""))


def line(fc: dict) -> str:
    """The one line brain status and the cockpit show."""
    pace, pct, r = fc.get("pace") or {}, fc.get("pct_now"), fc.get("reading")
    if pct is None:
        last = f"; {fc['readings']} reading(s), none converted" if fc["readings"] else ""
        return f"{fc['window']}: not known{last}; {fc['advice']} (brain usage quota)"
    head = f"{fc['window']} {pct:.0f} % now" + (
        f" (read {r['pct']:.0f} % at {r['at'][11:16]} UTC)" if r else " (estimated: no reading in this window)")
    if "at_reset" not in pace:
        return f"{head}; {fc['advice']} (brain usage quota)"
    reset = when(_dt(fc["resets"]))[:-4]
    if pace.get("full_at"):
        trend = (f"at the last {pace['hours']} h's pace 100 % on {when(_dt(pace['full_at']))[:-4]}, before the reset "
                 f"{reset} UTC")
    else:
        trend = f"at the last {pace['hours']} h's pace {pace['at_reset']:.0f} % at the reset {reset} UTC"
    return f"{head}; {trend}: {fc['advice']} (brain usage quota)"


def render(fc: dict) -> list[str]:
    """``brain usage quota``: the forecast, then the readings the conversion used."""
    out = [f"quota ({fc['window']}, {fc['plan'] or 'plan unknown'}): {fc['line']}"]
    if fc.get("resets"):
        h = fc["hours_left"] or 0
        out.append(f"  reset     {when(_dt(fc['resets']))}, in {int(h // 24)} d {h % 24:.0f} h")
    c = fc.get("conversion")
    u = fc.get("uncalibrated")
    if u:
        out.append(f"  convert   uncalibrated: {u['plan'] or 'the plan in force'} has {u['n']} of {u['needed']} "
                   f"converted reading(s) (readings of other plans are not used)")
    w5 = fc.get("window_5h")
    if w5:
        out.append(f"  5h window about {w5['pct_now']:.0f} % (read {w5['read_pct']:.0f} % at "
                   f"{w5['at'].replace('T', ' ')[:16]} UTC, {usage.usd(w5['since_usd'])} spent since), resets "
                   f"{w5['resets'].replace('T', ' ')[:16]} UTC")
    if c:
        out.append(f"  convert   {c['pct_per_usd']:.4f} % per $ at API prices ({usage.usd(c['usd_per_pct'])} per 1 %; "
                   f"the {fc['window']} window is about {usage.usd(c['quota_usd'])}), median of {c['n']} reading(s) "
                   f"over {FACTOR_DAYS} d")
    r = fc.get("reading")
    if r:
        out.append(f"  reading   {r['pct']:.0f} % at {r['at'].replace('T', ' ')[:16]} UTC, "
                   f"{usage.usd(r['since_usd'])} spent since")
    p = fc.get("pace")
    if p:
        tail = (f" -> {p['at_reset']:.0f} % at the reset" if "at_reset" in p else "") + (
            f", 100 % on {when(_dt(p['full_at']))}" if p.get("full_at") else "")
        out.append(f"  pace      last {p['hours']} h {usage.usd(p['usd'])} ({usage.usd(p['usd_h'])}/h, "
                   f"{p['pct_h']:.2f} %/h){tail}")
    sh = fc.get("session_hour")
    if sh:
        out.append(f"  session-h {usage.usd(sh['usd'])} per session-hour at API prices, its agents included "
                   f"({sh['hours']} session-hour(s), {usage.usd(sh['total_usd'])} over {sh['days']} d)")
    lv = fc.get("live")
    if lv:
        out.append(f"  live      {lv['sessions']} session(s), {usage.usd(lv['last_hour_usd'])} in the last hour; "
                   f"what they serve has about {usage.usd(lv['left_usd'])} left"
                   + (f" ({lv['left_pct']:.1f} %)" if lv.get("left_pct") is not None else ""))
    q = fc.get("queue")
    if q:
        fit = (f"; {q['room_pct']:.0f} % left after the live sessions: {q['fit']} fit ({usage.usd(q['fit_usd'])})"
               if "room_pct" in q else "")
        out.append(f"  queue     {q['items']} startable P0/P1 item(s), {usage.usd(q['usd'])} estimated{fit}"
                   + (f"; first {', '.join(q['first'])}" if q["first"] else ""))
    out.append(f"  advice    {fc['advice']}")
    if c:
        out.append("  readings")
        out += [f"    {x['at'].replace('T', ' ')[:16]} UTC {x['pct']:.0f} % (resets {x['resets'][:16].replace('T', ' ')})"
                f"{' on ' + x['host'] if x.get('host') else ''}: {usage.usd(x['usd'])} since the window started, "
                f"{x['pct_per_usd']:.4f} %/$" for x in c["readings"][-5:]]
    return out


def save_status(fc: dict) -> None:
    """``<BRAIN_HOME>/usage/quota.json``: the last forecast, the cockpit's to read."""
    f = status_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"v": 1, **fc}, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, f)


def load_status() -> dict:
    """The last forecast written ({} without one): what the cockpit shows without computing."""
    try:
        data = json.loads(status_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def run(led: cost.Ledger, projs: list[projects.Project], now: datetime, window: str = "week",
        plan: bool = True, plans=None) -> dict:
    """The forecast for ``led`` (every row: the quota is the account's) with the live sessions and ``projs``' queue
    when ``plan``, written to ``quota.json``."""
    readings = load_readings()
    live = queue = None
    if plan:
        est = estimator(led)
        live = live_of(led, now, est)
        queue = queue_of(led, projs, live["items"], est)
    fc = forecast(led.rows, readings, now, window, live, queue, plans)
    try:
        save_status(fc)
    except OSError:
        pass
    return fc


def status_of(projs: list[projects.Project], root: Path | None, now: datetime, quick: bool = False) -> dict:
    """brain status's quota row: the ledger as it is (brain status scanned it for the tokens row) joined to
    ``projs``; ``quick``: its rows only, without the live sessions or the queue (no graph read)."""
    try:
        plans = usage.plans_from(config.load(root).get("usage")) if root else None
        if quick:
            fc = forecast(list(usage.load().values()), load_readings(), now, plans=plans)
            save_status(fc)
            return fc
        return run(cost.load(projs, root, refresh=False), projs, now, plans=plans)
    except (OSError, ValueError) as exc:
        return {"error": str(exc)}
