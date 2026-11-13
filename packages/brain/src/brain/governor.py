"""The governor's usage-enforce hook (wi-brain-usage-enforce; ADRs on Remote Control and ultracode
and SCALE-1 to SCALE-3 of the scale study, 2026-11-03): a PreToolUse check on what spends the plan's quota by the
session-hour, at zero token, before the call.

It runs on three tools: a new session (``mcp__<server>__start_session``, the desktop app's), a subagent (``Agent``,
``Task``) and a workflow (``Workflow``). It reads only cached state: the quota readings the sessions note
(``brain usage quota --observe``: ``<BRAIN_HOME>/usage/quota.jsonl``) and the last forecast (``usage/quota.json``),
the desktop app's session files (``%LOCALAPPDATA%/Claude-Data/*/claude-code-sessions``, read only, as brain.tidy),
the session records the Stop hook writes (``<BRAIN_HOME>/sessions/<id>.json``), the machine's committed memory and
available RAM, and
its configuration resolved once and cached in ``<BRAIN_HOME>/cache/governor.json`` while config.json and the
registry keep their mtime and size. Its decision takes under 50 ms (tests/test_governor.py checks it).

The checks, in order; the first that holds decides:

- ``critical``: a window in force (the week, and the 5-hour one when get_usage shows it and a reading of it is noted)
  at ``critical`` % used or more: deny, for every tool (SCALE-1: ST-4 covers only the master's context threshold).
- ``stale``: a new session or a workflow while the newest reading is older than ``fresh_minutes``, on a machine that
  noted one in the last 7 days: deny, with the commands that note both windows (get_usage, then brain usage quota
  --observe): every start reads the quota first. A machine that never notes a reading is not checked.
- ``memory``: a new session or a workflow while the machine's committed memory (Windows: what it promised, RAM plus
  page file, in % of its commit limit; elsewhere the memory in use) is at ``memory`` % or more, or its available RAM
  (what is free now) is under ``memory_available_gb`` GB (default 0: no floor; the owner opts in): deny, naming both measures and the one that refused
  (wi-brain-memory-guard-two-measures: committed memory alone sat at 93-96 % with 24 GB of RAM free).
- ``sessions``: a new session while the sessions running in parallel (the app's sessions not archived and active in
  the last ``live_minutes``; without the app, the session records written in that time) reach the cap: the smaller of
  ``sessions`` and what the week's room pays for, ``(100 - pct) x $ per % / (wave_hours x session_hour_usd)`` minus
  the master (scale study gap 1). With ``session_hour_measured`` true (default false), the session-hour is the
  measured one (brain.quota's, its subagents and workflow agents included, in ``usage/quota.json``) when it is above
  ``session_hour_usd``; by default the measured value is shown, never applied.
- ``brainstorms``: a new brainstorm while ``brainstorms`` are open on the machine (every project; SCALE-2/3): the cap
  is config.json's, which a project's ``usage: {brainstorms: N}`` in projects.yaml may lower for itself, never raise.
  A session is a brainstorm when its brief says ``Task class: brainstorm`` or carries ``#brainstorm`` (the session
  record's ``task_class``), or its title matches ``brainstorm_title`` (default: it starts with "Brainstorm"); an
  open brainstorm is one not archived and active in the last ``brainstorm_hours``. A brainstorm start this hook lets
  through is noted in ``usage/starts.jsonl``, so the next start counts it before its first turn ends (a log rotated
  monthly, two months kept, brain.stateio: the hook reads the live file and the newest monthly one, so a start just
  before the month turned still counts; the quota readings likewise).
- ``streams`` and ``wave_quota`` (wi-brain-wave-quota-gate; RETRO-5 of the waves retro, 2026-11-03: by the quota,
  three streams at most with their reviews), only with config.json ``usage.guard.wave_quota`` (absent: off) and only
  for a start_session call that starts a session now (``initiation`` user_asked or none, or a ``proposal_id``; a
  proposal card starts nothing). ``streams``: deny when the calling session (the master) already has
  ``max_streams`` live children: the desktop app's children of that session (``spawnedFrom``), neither archived nor
  detached, that are *running* (their transcript written in the last ``live_minutes`` and its last turn not ended)
  or *starting* (created in the last 10 minutes, no transcript yet), plus the stream starts this hook let through that
  the app does not show yet (``usage/starts.jsonl``). ``wave_quota``: ask the owner when the week's forecast at its
  reset (the week's percent now, as below, plus the last forecast's pace, ``usage/quota.json``'s ``pace.pct_h``, times
  the hours to the reset) plus this stream's cost in percent of the week goes over ``ask_over_pct``. The stream's
  cost is the brief's estimate (the ``usd=`` of its Cost estimate line, brain brief, brain cost estimate), else the
  median session's (the forecast's ``live.median_session_usd``), converted by the forecast's ``pct_per_usd``. Either
  check fails open: a forecast that cannot be read, a session the app does not know, a count that takes more than
  :data:`STREAM_BUDGET_S` let the call through with a note in the hook's context. ``0`` turns either check off.
  :func:`wave_room` gives the same answer as a count of the streams that fit now (brain brief, brain wave plan, brain
  usage guard).
- ``warn``: a window at ``warn`` % or more: ask the owner, for every tool.

The thresholds and caps are config.json's ``usage.guard`` (:data:`DEFAULTS`), never rule text. A refusal names the
reason and the owner's ways to override: ``brain usage allow [--hours H]`` in their own terminal (the guards refuse it
to a session, and any write of its file), or ``BRAIN_GUARD_ALLOW=usage`` in Claude Code's environment. Refusals, asks
and overrides go to the guards ledger (``guard: usage``, the check that decided). Any error lets the call through and
goes to ``ledger/errors.log``: the hook never breaks a session.

Not applied here: ``CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS`` (the workflow agents running at once, ~8 from the
scale study) is Claude Code's own setting, the owner's to apply through their installer, never a session's.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import midsession, paths, stateio, timing

GUARD = "usage"
DEFAULTS = {"enabled": True, "warn": 80.0, "critical": 95.0, "sessions": 8, "brainstorms": 2, "memory": 97.0,
            "memory_available_gb": 0.0, "wave_hours": 4.0, "session_hour_usd": 14.0, "session_hour_measured": False,
            "fresh_minutes": 60, "live_minutes": 30,
            "brainstorm_hours": 12, "brainstorm_title": r"^\W*brainstorm\b", "wave_quota": None}
# usage.guard.wave_quota's fields when it is given (wi-brain-wave-quota-gate; RETRO-5): absent, the gate is off
WAVE_DEFAULTS = {"ask_over_pct": 90.0, "max_streams": 3}
STREAM_BUDGET_S = 2.0   # the live streams' count gives up past this (the call goes through, with a note)
STREAM_STATES = ("running", "starting")   # what counts as a live stream (asking, idle, quiet do not)
_USD_RE = re.compile(r"\busd=\$?(\d+(?:\.\d+)?)")
LOWER_ONLY = ("sessions", "brainstorms")   # what a project's usage: may lower for itself, never raise
SESSION_TOOL = re.compile(r"^mcp__.+__start_session$")
AGENT_TOOLS = ("Agent", "Task")
WORKFLOW_TOOLS = ("Workflow",)
BRAINSTORM_BRIEF = re.compile(r"task class\W{0,8}brainstorm\b|#brainstorm\b", re.I)
WINDOWS = {"week": timedelta(days=7), "5h": timedelta(hours=5)}
OPTED_IN = timedelta(days=7)        # a machine with a reading this recent is checked for stale readings
PENDING = timedelta(minutes=10)     # a brainstorm start counts this long before the app shows its session
ALLOW_HOURS = 2.0


def kind(tool: str) -> str:
    """session, agent, workflow, or '' for a tool the governor does not check."""
    if SESSION_TOOL.match(tool or ""):
        return "session"
    return "agent" if tool in AGENT_TOOLS else "workflow" if tool in WORKFLOW_TOOLS else ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(text) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        dt = datetime.fromisoformat(re.sub(r"Z$", "+00:00", text.strip()))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(f: Path):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _stat(f: Path):
    try:
        st = os.stat(f)
        return [st.st_mtime_ns, st.st_size]
    except OSError:
        return None


# --- configuration, cached ---------------------------------------------------------------------------------------

def limits_of(data: dict | None) -> tuple[dict, list[str]]:
    """config.json's usage.guard over :data:`DEFAULTS`, and what is wrong in it (a value of the wrong type is left at
    its default)."""
    out, errors = dict(DEFAULTS), []
    given = data if isinstance(data, dict) else {}
    for key, value in given.items():
        if key not in DEFAULTS:
            errors.append(f"usage.guard.{key}: unknown (known: {', '.join(DEFAULTS)})")
            continue
        if key == "wave_quota":
            out[key], errs = wave_quota_of(value)
            errors += errs
            continue
        want = type(DEFAULTS[key])
        ok = isinstance(value, bool) if want is bool else isinstance(value, str) if want is str else \
            isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
        if not ok:
            errors.append(f"usage.guard.{key}: {'true or false' if want is bool else 'a string' if want is str else 'a number of 0 or more'}")
            continue
        out[key] = value
    try:
        re.compile(out["brainstorm_title"])
    except re.error as exc:
        errors.append(f"usage.guard.brainstorm_title: not a regular expression ({exc})")
        out["brainstorm_title"] = DEFAULTS["brainstorm_title"]
    return out, errors


def wave_quota_of(value) -> tuple[dict | None, list[str]]:
    """usage.guard.wave_quota over :data:`WAVE_DEFAULTS` (None: the gate is off), and what is wrong in it (a field of
    the wrong type is left at its default)."""
    if value is None:
        return None, []
    if not isinstance(value, dict):
        return None, [f"usage.guard.wave_quota: a mapping of {', '.join(WAVE_DEFAULTS)} (the gate stays off)"]
    out, errors = dict(WAVE_DEFAULTS), []
    for key, v in value.items():
        number = isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
        if key == "ask_over_pct" and number and v <= 100:
            out[key] = float(v)
        elif key == "max_streams" and number and isinstance(v, int):
            out[key] = v
        elif key in WAVE_DEFAULTS:
            errors.append(f"usage.guard.wave_quota.{key}: " + ("a number from 0 to 100" if key == "ask_over_pct"
                                                               else "a whole number of 0 or more"))
        else:
            errors.append(f"usage.guard.wave_quota.{key}: unknown (known: {', '.join(WAVE_DEFAULTS)})")
    return out, errors


def project_limits(entry) -> tuple[dict, list[str]]:
    """A registry entry's usage: {sessions, brainstorms}, whole numbers of 0 or more, and what is wrong in it."""
    usage = entry.get("usage") if isinstance(entry, dict) else None
    if usage is None:
        return {}, []
    if not isinstance(usage, dict):
        return {}, [f"usage is a mapping of {', '.join(LOWER_ONLY)}"]
    out, errors = {}, []
    for key, value in usage.items():
        if key not in LOWER_ONLY:
            errors.append(f"usage.{key}: unknown (known: {', '.join(LOWER_ONLY)})")
        elif not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"usage.{key}: a whole number of 0 or more")
        else:
            out[key] = value
    return out, errors


def _sources(cwd: str) -> list:
    env = [os.environ.get(k) for k in ("BRAIN_CONFIG", "BRAIN_PROJECTS", "CLAUDE_BRAIN_DIR", "BRAIN_PERSONAL")]
    files = [Path(e).expanduser() for e in env[:2] if e]
    for base in paths.bases(cwd):
        files += [base / "config.json", base / "projects.yaml"]
    # the defaults are part of the key: an engine with other defaults never reads the limits an older one cached
    return [env, json.dumps(DEFAULTS, sort_keys=True), *[[str(f), _stat(f)] for f in files]]


def settings(cwd: str) -> dict:
    """{limits, errors, projects: {name: {roots, limits}}, owner, plugin, master_budget}: built from config.json and the registry
    (brain.config, brain.projects, PyYAML: ~100 ms), kept in <BRAIN_HOME>/cache/governor.json under the key of their
    files' mtimes and sizes (~1 ms)."""
    key = _sources(cwd)
    cache = paths.brain_home() / "cache" / "governor.json"
    kept = _read_json(cache)
    if isinstance(kept, dict) and kept.get("key") == key and isinstance(kept.get("settings"), dict):
        return kept["settings"]
    from . import config, projects   # the slow path: only when a source changed

    cfg = config.load(Path(cwd) if cwd else None)
    usage = cfg.data.get("usage") if isinstance(cfg.data.get("usage"), dict) else {}
    lim, errors = limits_of(usage.get("guard"))
    projs: dict = {}
    try:
        raw = projects.raw(cfg.root)
        for p in projects.guarded(cfg.root):   # a project not loaded yet keeps its caps
            name = p.name
            own, errs = project_limits(raw.get(name))
            errors += [f"project {name}: {e}" for e in errs]
            roots = [str(p.root), *map(str, p.production)]
            projs[name] = {"roots": [os.path.normcase(os.path.abspath(r)) for r in roots], "limits": own}
    except (Exception, SystemExit) as exc:   # a registry that does not load leaves the global caps
        errors.append(f"registry: {exc}")
    mb = usage.get("master_budget")   # a master's budget without a brief (brain.sessions, brain.budget)
    out = {"limits": lim, "errors": errors, "projects": projs, "owner": config.owner(cfg),
           "plugin": config.claude(cfg)["plugin"],
           "master_budget": mb if isinstance(mb, int) and not isinstance(mb, bool) and mb > 0 else None}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "settings": out}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return out


def project_of(folder: str, st: dict) -> str:
    """The registered project whose root (or production checkout) holds ``folder``, the deepest; '' for none."""
    f = os.path.normcase(os.path.abspath(folder or "."))
    best, depth = "", -1
    for name, p in st["projects"].items():
        for r in p["roots"]:
            if (f == r or f.startswith(r.rstrip("\\/") + os.sep)) and len(r) > depth:
                best, depth = name, len(r)
    return best


def caps(st: dict, project: str) -> dict:
    """The caps in force for ``project``: config.json's, each lowered by the project's own, never raised."""
    lim = dict(st["limits"])
    own = (st["projects"].get(project) or {}).get("limits") or {}
    for k in LOWER_ONLY:
        if k in own:
            lim[k] = min(lim[k], own[k])
    return lim


# --- the quota -----------------------------------------------------------------------------------------------------

def _tail_lines(f: Path, size: int = 65536) -> list[str]:
    try:
        with open(f, "rb") as fh:
            fh.seek(0, 2)
            n = fh.tell()
            fh.seek(max(0, n - size))
            return fh.read().decode("utf-8", "replace").splitlines()[1 if n > size else 0:]
    except OSError:
        return []


def _tail_log(f: Path, size: int = 65536) -> list[str]:
    """The last lines of a rotated log (brain.stateio.rotate_log): the tail of its newest monthly file, then of the live
    one, so that the month's turn hides nothing recent."""
    return [line for p in stateio.log_files(f)[-2:] for line in _tail_lines(p, size)]


def quota_now(now: datetime, lim: dict) -> dict:
    """The windows in force, {window: {pct, at, how}} (how: read, the reading as noted; forecast, the last brain
    usage quota's percent now; plus the week's last pace up to fresh_minutes past it), the newest reading's time,
    whether the machine notes readings, and the $ per % of the week."""
    home = paths.brain_home() / "usage"
    readings = []
    for line in _tail_log(home / "quota.jsonl"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("window") in WINDOWS and isinstance(r.get("pct"), (int, float)) \
                and _dt(r.get("at")) and _dt(r.get("resets")):
            readings.append(r)
    status = _read_json(home / "quota.json")
    status = status if isinstance(status, dict) else {}
    newest = max((_dt(r["at"]) for r in readings), default=None)
    out: dict = {"windows": {}, "newest": _iso(newest) if newest else None,
                 "opted_in": bool(newest and newest >= now - OPTED_IN), "usd_per_pct": None}
    conv = status.get("conversion") if isinstance(status.get("conversion"), dict) else {}
    if isinstance(conv.get("usd_per_pct"), (int, float)) and not isinstance(conv["usd_per_pct"], bool) \
            and conv["usd_per_pct"] > 0:
        out["usd_per_pct"] = float(conv["usd_per_pct"])
    sh = status.get("session_hour") if isinstance(status.get("session_hour"), dict) else {}
    out["session_hour_usd"] = float(sh["usd"]) if isinstance(sh.get("usd"), (int, float)) and sh["usd"] > 0 else None
    for w in WINDOWS:
        live = [r for r in readings if r["window"] == w and _dt(r["resets"]) > now >= _dt(r["at"]) - timedelta(minutes=5)]
        if not live:
            continue
        r = max(live, key=lambda x: _dt(x["at"]))
        pct, at, how = float(r["pct"]), _dt(r["at"]), "read"
        if w == "week" and status.get("window") == "week" and isinstance(status.get("pct_now"), (int, float)):
            s_at, s_resets = _dt(status.get("now")), _dt(status.get("resets"))
            if s_at and s_resets and s_resets > now and s_at > at and abs(s_resets - _dt(r["resets"])) < \
                    timedelta(minutes=5):
                pct, at, how = float(status["pct_now"]), s_at, "forecast"
        pace = (status.get("pace") or {}).get("pct_h") if w == "week" else None
        if isinstance(pace, (int, float)) and pace > 0:
            hours = min(max(0.0, (now - at).total_seconds() / 3600), lim["fresh_minutes"] / 60)
            pct += pace * hours
            how += f" + {pace:.2f} %/h x {hours:.1f} h"
        out["windows"][w] = {"pct": round(min(pct, 100.0), 1), "at": _iso(at), "how": how,
                             "resets": r["resets"]}
    # what the wave quota gate projects with (wi-brain-wave-quota-gate): the last forecast's pace, only while that
    # forecast is of the week in force (its reset the reading's), its conversion and the median session's cost
    week, s_resets = out["windows"].get("week"), _dt(status.get("resets"))
    pace = status.get("pace") if isinstance(status.get("pace"), dict) else {}
    pct_h = pace.get("pct_h")
    out["pace_pct_h"] = float(pct_h) if (week and status.get("window") == "week" and s_resets and isinstance(
        pct_h, (int, float)) and not isinstance(pct_h, bool) and pct_h >= 0
        and abs(s_resets - _dt(week["resets"])) < timedelta(minutes=5)) else None
    ppu = conv.get("pct_per_usd")
    out["pct_per_usd"] = float(ppu) if isinstance(ppu, (int, float)) and not isinstance(ppu, bool) and ppu > 0 else \
        (1 / out["usd_per_pct"] if out["usd_per_pct"] else None)
    live = status.get("live") if isinstance(status.get("live"), dict) else {}
    med = live.get("median_session_usd")
    out["median_session_usd"] = float(med) if isinstance(med, (int, float)) and med > 0 else None
    return out


# --- the sessions --------------------------------------------------------------------------------------------------

def app_sessions(now: datetime, horizon: timedelta) -> list[dict] | None:
    """The desktop app's sessions whose file changed within ``horizon``: {id, cli, title, archived, active (its last
    activity), created}; None when the app is not on this machine. Each file is parsed once per change (a cache in
    <BRAIN_HOME>/cache/governor-app.json)."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    root = Path(base) / "Claude-Data"
    files = [*root.glob("*/claude-code-sessions/*/*/local_*.json")]
    if not files:
        return None if not any(root.glob("*/claude-code-sessions")) else []
    cache_f = paths.brain_home() / "cache" / "governor-app.json"
    cache = _read_json(cache_f)
    cache = cache if isinstance(cache, dict) else {}
    out, fresh, changed = [], {}, False
    floor = (now - horizon).timestamp()
    for f in files:
        st = _stat(f)
        if not st or st[0] / 1e9 < floor:
            continue
        key = str(f)
        hit = cache.get(key)
        if not (isinstance(hit, dict) and hit.get("stat") == st):
            data = _read_json(f)
            if not isinstance(data, dict) or not data.get("sessionId"):
                continue
            hit = {"stat": st, "id": str(data["sessionId"]), "cli": str(data.get("cliSessionId") or ""),
                   "title": str(data.get("title") or ""), "archived": bool(data.get("isArchived")),
                   "active": data.get("lastActivityAt"), "created": data.get("createdAt")}
            changed = True
        fresh[key] = hit
        out.append(hit)
    if changed or set(fresh) != set(cache):
        try:
            cache_f.parent.mkdir(parents=True, exist_ok=True)
            cache_f.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return out


def _ms(dt: datetime) -> float:
    return dt.timestamp() * 1000


def _record_class(cli: str) -> str:
    """The task class the session record of ``cli`` holds (its brief's), else ''."""
    if not cli:
        return ""
    sr = _read_json(paths.sessions_dir() / f"{cli}.json")
    return str(sr.get("task_class") or "") if isinstance(sr, dict) else ""


def _starts(now: datetime) -> list[dict]:
    """The brainstorm starts this hook let through in the last :data:`PENDING`."""
    out = []
    for line in _tail_log(paths.brain_home() / "usage" / "starts.jsonl", 16384):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        at = _dt(r.get("at")) if isinstance(r, dict) else None
        if at and now - PENDING <= at <= now + timedelta(minutes=1) and r.get("brainstorm"):
            out.append(r)
    return out


def sessions_now(now: datetime, lim: dict) -> dict:
    """{running, brainstorms, source, brainstorm_titles}: the sessions running in parallel and the open brainstorms,
    from the app's session files (else the session records), plus the brainstorm starts not shown yet."""
    live = timedelta(minutes=lim["live_minutes"])
    bs_horizon = timedelta(hours=lim["brainstorm_hours"])
    title_re = re.compile(lim["brainstorm_title"], re.I)
    app = app_sessions(now, max(live, bs_horizon))
    running, brainstorms, titles = 0, 0, []
    pending = _starts(now)
    if app is not None:
        source = "app"
        for s in app:
            if s["archived"]:
                continue
            active = s["active"] if isinstance(s["active"], (int, float)) else 0
            if active >= _ms(now - live):
                running += 1
            if active < _ms(now - bs_horizon):
                continue
            started = [p for p in pending if p.get("title") == s["title"] and isinstance(s["created"], (int, float))
                       and s["created"] >= _ms(_dt(p["at"])) - 60_000]
            for p in started:
                pending.remove(p)
            if started or title_re.search(s["title"]) or _record_class(s["cli"]) == "brainstorm":
                brainstorms += 1
                titles.append(s["title"])
    else:
        source = "records"
        d = paths.sessions_dir()
        try:
            entries = list(os.scandir(d))
        except OSError:
            entries = []
        for e in entries:
            if not e.name.endswith(".json") or e.name.count(".") > 1:
                continue
            m = e.stat().st_mtime
            if m >= (now - live).timestamp():
                running += 1
            if m >= (now - bs_horizon).timestamp() and _record_class(e.name[:-5]) == "brainstorm":
                brainstorms += 1
                titles.append(e.name[:-5])
    brainstorms += len(pending)
    titles += [str(p.get("title") or "") for p in pending]
    return {"running": running, "brainstorms": brainstorms, "source": source, "brainstorm_titles": titles}


def is_brainstorm(inp: dict, lim: dict) -> bool:
    """Whether a start_session call starts a brainstorm: its brief's class or tag, or its title."""
    brief = "\n".join(str(inp.get(k) or "") for k in ("prompt", "background"))
    title = str(inp.get("title") or "")
    return bool(BRAINSTORM_BRIEF.search(brief) or BRAINSTORM_BRIEF.search(title)
                or re.search(lim["brainstorm_title"], title, re.I))


# --- the wave quota gate (wi-brain-wave-quota-gate) ----------------------------------------------------------------

def starts_now(inp: dict) -> bool:
    """Whether a start_session call starts a session now: the owner asked for it (``initiation`` user_asked, or none)
    or it starts a proposal (``proposal_id``); a proposal card (``offer``, ``own_initiative``) starts nothing
    (brain.budget counts a master's children the same way)."""
    return bool(inp.get("proposal_id")) or inp.get("initiation") in ("user_asked", None)


def estimate_usd(text: str) -> float | None:
    """The ``usd=N`` of a cost estimate's line (brain cost estimate, brain brief's « Cost estimate »), else None."""
    m = _USD_RE.search(str(text or ""))
    return float(m.group(1)) if m else None


def stream_usd(inp: dict, q: dict) -> tuple[float | None, str]:
    """(the cost of the stream a start_session call starts, where it comes from): the brief's estimate (its
    ``usd=``), else the median session's of the last forecast, else (None, 'no estimate')."""
    usd = estimate_usd("\n".join(str(inp.get(k) or "") for k in ("prompt", "background", "title")))
    if usd is not None:
        return usd, "the brief's estimate"
    if q.get("median_session_usd"):
        return q["median_session_usd"], "the median session's cost, the brief giving no estimate"
    return None, "no estimate"


def projection(q: dict, now: datetime) -> dict | None:
    """The week's forecast at its reset: its percent now (:func:`quota_now`) plus the last forecast's pace times the
    hours left; None when a part is missing (no week reading in force, no pace of this week, no conversion)."""
    week = q["windows"].get("week")
    if not week or q.get("pace_pct_h") is None or not q.get("pct_per_usd"):
        return None
    resets = _dt(week["resets"])
    hours = max(0.0, (resets - now).total_seconds() / 3600) if resets else 0.0
    return {"now_pct": week["pct"], "pct_h": q["pace_pct_h"], "hours_left": round(hours, 1),
            "at_reset": round(week["pct"] + q["pace_pct_h"] * hours, 1), "resets": week["resets"],
            "pct_per_usd": q["pct_per_usd"]}


def _turn(records: list[dict]) -> str:
    """Where a transcript's turn is from its last records: ``asking``, ``idle`` or ``active``; brain.cockpit.turn's
    reading (a stop hook's summary ends a turn), kept here because the cockpit's import costs a second in a hook."""
    for r in reversed(records):
        kind_ = r.get("type")
        if kind_ == "system":
            if r.get("subtype") == "stop_hook_summary":
                return "idle"
            continue
        if kind_ == "assistant":
            msg = r.get("message") if isinstance(r.get("message"), dict) else {}
            content = msg.get("content") if isinstance(msg.get("content"), list) else []
            uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            if any(b.get("name") == "AskUserQuestion" for b in uses):
                return "asking"
            if not uses and msg.get("stop_reason") == "end_turn":
                return "idle"
            return "active"
        if kind_ == "user":
            return "active"
    return "active"


def _project_dirs() -> list[str]:
    """Claude Code's transcript folders, listed once per count (paths.find_transcript globs them for each child)."""
    try:
        return [d.path for d in os.scandir(paths.projects_dir()) if d.is_dir()]
    except OSError:
        return []


def _transcript_of(sid: str, dirs: list[str]) -> Path | None:
    """The newest main transcript of ``sid`` in ``dirs``, or None."""
    hits = [p for p in (Path(d) / f"{sid}.jsonl" for d in dirs) if p.is_file()]
    return max(hits, key=lambda p: _stat(p) or [0], default=None)


def child_state(node: dict, now: datetime, lim: dict, dirs: list[str] | None = None) -> str:
    """A child's state for the streams cap: ``starting`` (created in the last :data:`PENDING`, no transcript yet),
    ``running`` (its transcript written in the last ``live_minutes`` and its turn not ended), else ``asking``,
    ``idle``, ``quiet`` (no write for ``live_minutes``) or ``unknown`` (no transcript, not new)."""
    created = node.get("created")
    young = isinstance(created, (int, float)) and not isinstance(created, bool) and \
        created >= _ms(now - PENDING)
    sid = str(node.get("session") or "")
    f = _transcript_of(sid, _project_dirs() if dirs is None else dirs) if sid else None
    if f is None:
        return "starting" if young else "unknown"
    try:
        age = now.timestamp() - f.stat().st_mtime
    except OSError:
        return "starting" if young else "unknown"
    if age > lim["live_minutes"] * 60:
        return "quiet"
    records = []
    for line in _tail_lines(f, 65536):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    t = _turn(records)
    return "running" if t == "active" else t


def _stream_starts(now: datetime, by: str) -> list[dict]:
    """The stream starts this hook let through for session ``by`` in the last :data:`PENDING`."""
    out = []
    for line in _tail_log(paths.brain_home() / "usage" / "starts.jsonl", 16384):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        at = _dt(r.get("at")) if isinstance(r, dict) else None
        if at and now - PENDING <= at <= now + timedelta(minutes=1) and r.get("stream") and r.get("by") == by:
            out.append(r)
    return out


def live_streams(master: str, now: datetime, lim: dict, budget_s: float | None = None) -> dict:
    """The live streams of ``master`` (its app id or its transcript's): {n, names, host_id, note}; ``n`` is None, with
    the reason in ``note``, when they cannot be counted (no app on the machine, a session the app does not know, a
    count past ``budget_s``)."""
    from . import sessions  # ~35 ms, only for a start the gate checks
    t0 = time.monotonic()
    budget_s = STREAM_BUDGET_S if budget_s is None else budget_s
    idx = sessions.app_index()
    if idx is None:
        return {"n": None, "names": [], "note": "the desktop app's sessions are not on this machine"}
    host = master if master in idx else next((h for h, m in idx.items() if master and m.get("session") == master), "")
    if not host:
        return {"n": None, "names": [], "note": "this session is not one of the desktop app's"}
    kids = sorted((m for m in idx.values() if m.get("parent") == host and not m.get("archived")
                   and m.get("detached") is not True), key=lambda m: -(m.get("created") or 0))
    names, shown, dirs = [], [], _project_dirs() if kids else []
    for m in kids:
        if time.monotonic() - t0 > budget_s:
            return {"n": None, "names": [], "note": f"the live streams were not counted within {budget_s:g} s"}
        if child_state(m, now, lim, dirs) in STREAM_STATES:
            names.append(str(m.get("name") or m.get("title") or m.get("host_id")))
        shown.append(m)
    by = str((idx.get(host) or {}).get("session") or master)
    pending = []
    for r in _stream_starts(now, by):   # a start the app does not show yet: no child of the title since
        at = _ms(_dt(r["at"])) - 60_000
        hit = next((m for m in shown if isinstance(m.get("created"), (int, float)) and m["created"] >= at
                    and (not r.get("title") or m.get("title") == r.get("title"))), None)
        if hit is not None:
            shown.remove(hit)
        else:
            pending.append(str(r.get("title") or "a proposal started"))
    return {"n": len(names) + len(pending), "names": names + pending, "host_id": host, "note": ""}


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


def wave_state(wq: dict, inp: dict, master: str, now: datetime, lim: dict, q: dict) -> dict:
    """What the gate sees for one start: the forecast at the reset, this stream's cost, the master's live streams and
    the notes of what could not be read (it fails open)."""
    out: dict = {**wq, "projection": None, "usd": None, "usd_basis": "", "item_pct": None, "streams": {"n": None},
                 "notes": []}
    try:
        if wq["ask_over_pct"]:
            p = out["projection"] = projection(q, now)
            out["usd"], out["usd_basis"] = stream_usd(inp, q)
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


def wave_room(cwd: str, master: str, usds: list[float | None], now: datetime | None = None) -> dict | None:
    """How many streams fit now (brain brief, brain wave plan, brain usage guard): the streams left to ``master``
    (max_streams less its live ones) and those whose costs ``usds`` (in order; None: the median session's) fit under
    ask_over_pct at the reset; ``fit`` the smaller of the two known ones. None while usage.guard.wave_quota is off."""
    now = now or _now()
    st = settings(cwd)
    lim = st["limits"]
    wq = lim.get("wave_quota")
    if not lim["enabled"] or not wq:
        return None
    q = quota_now(now, lim)
    w = wave_state(wq, {}, master, now, lim, q)
    p = w["projection"]
    costs = [u if u is not None else q.get("median_session_usd") for u in usds]
    pcts = [None if p is None or c is None else round(c * p["pct_per_usd"], 2) for c in costs]   # as item_pct
    by_quota = _fit(p and p["at_reset"], pcts, wq["ask_over_pct"]) if wq["ask_over_pct"] else None
    n = w["streams"].get("n")
    by_streams = max(0, wq["max_streams"] - n) if wq["max_streams"] and n is not None else None
    known = [x for x in (by_quota, by_streams) if x is not None]
    w.update(by_quota=by_quota, by_streams=by_streams, fit=min(known) if known else None, pcts=pcts)
    w["line"] = wave_line(w)
    return w


def wave_line(w: dict) -> str:
    """One line of :func:`wave_room`: the streams that fit now and why."""
    p, s = w["projection"], w["streams"]
    parts = []
    if w["ask_over_pct"]:
        if p is None:
            parts.append("by the quota: not known (brain usage quota)")
        else:
            cost = next((x for x in w.get("pcts") or [] if x is not None), None)
            parts.append(f"by the quota {w['by_quota'] if w['by_quota'] is not None else '?'}: the week "
                         f"{p['now_pct']:.0f} % now, {p['at_reset']:.0f} % at its reset "
                         f"{p['resets'][:16].replace('T', ' ')} UTC at the last forecast's pace, asked over "
                         f"{w['ask_over_pct']:g} %" + (f", a stream {cost:.1f} %" if cost is not None else ""))
    if w["max_streams"]:
        if s.get("n") is None:
            parts.append(f"by the streams: not known ({s.get('note') or 'no master session'})")
        else:
            parts.append(f"by the streams {w['by_streams']}: {s['n']} live of {w['max_streams']}"
                         + (f" ({', '.join(s['names'][:4])})" if s.get("names") else ""))
    fit = w.get("fit")
    return f"{fit if fit is not None else 'not known'} ({'; '.join(parts)}; usage.guard.wave_quota)"


# --- the machine ---------------------------------------------------------------------------------------------------

def memory_info() -> dict:
    """The machine's two memory measures: {committed, available_gb}. ``committed``: Windows' commit charge in % of its
    commit limit (what it promised, RAM plus page file), elsewhere the memory in use in % (/proc/meminfo);
    ``available_gb``: the RAM available now, in GB. A measure that cannot be read is None."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class Info(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("CommitTotal", ctypes.c_size_t),
                            ("CommitLimit", ctypes.c_size_t), ("CommitPeak", ctypes.c_size_t),
                            ("PhysicalTotal", ctypes.c_size_t), ("PhysicalAvailable", ctypes.c_size_t),
                            ("SystemCache", ctypes.c_size_t), ("KernelTotal", ctypes.c_size_t),
                            ("KernelPaged", ctypes.c_size_t), ("KernelNonpaged", ctypes.c_size_t),
                            ("PageSize", ctypes.c_size_t), ("HandleCount", wintypes.DWORD),
                            ("ProcessCount", wintypes.DWORD), ("ThreadCount", wintypes.DWORD)]
            info = Info()
            info.cb = ctypes.sizeof(Info)
            if ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
                page = info.PageSize or 4096   # the counts are in pages
                return {"committed": round(100.0 * info.CommitTotal / info.CommitLimit, 1) if info.CommitLimit
                        else None, "available_gb": round(info.PhysicalAvailable * page / 2 ** 30, 1)}
        except (OSError, AttributeError, ValueError):
            pass
        return {"committed": None, "available_gb": None}
    try:
        text = Path("/proc/meminfo").read_text(encoding="ascii")
    except OSError:
        return {"committed": None, "available_gb": None}
    return meminfo(text)


def meminfo(text: str) -> dict:
    """The two measures from /proc/meminfo's text (kB): the memory in use in %, MemAvailable in GB."""
    kb = {m.group(1): int(m.group(2)) for m in re.finditer(r"^(\w+):\s+(\d+)", text, re.M)}
    avail = kb.get("MemAvailable")
    return {"committed": round(100.0 * (1 - avail / kb["MemTotal"]), 1) if kb.get("MemTotal") and avail is not None
            else None, "available_gb": round(avail / 2 ** 20, 1) if avail is not None else None}


def memory_pct() -> float | None:
    """The committed measure alone (:func:`memory_info`), None when it cannot be read."""
    return memory_info().get("committed")


def memory_text(committed: float | None, available_gb: float | None, lim: dict) -> str:
    """Both measures and their thresholds, in words: brain usage guard, a refusal, brain status."""
    c = f"{committed:.1f} % committed" if committed is not None else "committed unknown"
    a = f"{available_gb:.1f} GB of RAM available" if available_gb is not None else "available RAM unknown"
    floor = lim["memory_available_gb"]
    return f"{c} (refused from {lim['memory']:g} %), {a}" + (f" (refused under {floor:g} GB)" if floor else " (no floor)")


def memory_refusal(committed: float | None, available_gb: float | None, lim: dict) -> str:
    """'' when both measures let a start through, else the one that refuses, or 'both'."""
    over = committed is not None and committed >= lim["memory"]
    low = available_gb is not None and available_gb < lim["memory_available_gb"]
    return "both" if over and low else "committed" if over else "available" if low else ""


# --- the override --------------------------------------------------------------------------------------------------

def allow_file() -> Path:
    return paths.brain_home() / "usage" / "allow.json"


def override_until(now: datetime) -> dict | None:
    """The owner's override (brain usage allow) while it holds: {until, reason, at}, else None."""
    data = _read_json(allow_file())
    until = _dt(data.get("until")) if isinstance(data, dict) else None
    return data if until and until > now else None


def allow(hours: float = ALLOW_HOURS, reason: str = "", now: datetime | None = None) -> dict:
    """``brain usage allow``: lift the governor for ``hours`` (0: end the override now); the owner's, in their own
    terminal (brain.guards refuses it to a session)."""
    now = now or _now()
    f = allow_file()
    if hours <= 0:
        try:
            f.unlink()
        except OSError:
            pass
        return {}
    rec = {"v": 1, "at": _iso(now), "until": _iso(now + timedelta(hours=hours)), "reason": reason}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return rec


def _env_allowed() -> bool:
    names = {w.strip().lower() for w in os.environ.get("BRAIN_GUARD_ALLOW", "").split(",") if w.strip()}
    return bool(names & {"usage", "all"} or any(n.startswith("usage:") for n in names))


# --- the decision --------------------------------------------------------------------------------------------------

def _session_hour(lim: dict, q: dict) -> tuple[float, bool]:
    """The session-hour the sessions cap divides by, and whether it is the measured one. The measured session-hour
    (its agents' included, brain.quota) counts only when usage.guard.session_hour_measured is true, and then only
    above the configured one: by default the cap is the configured session_hour_usd's."""
    measured = q.get("session_hour_usd")
    applied = bool(lim["session_hour_measured"] and measured and measured > lim["session_hour_usd"])
    return (measured if applied else lim["session_hour_usd"]), applied


def state(payload: dict, now: datetime | None = None) -> dict:
    """What the governor sees for ``payload``: the tool's kind, the project, the caps, the quota, the sessions, the
    memory, the override."""
    now = now or _now()
    tool = payload.get("tool_name") or ""
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    cwd = str(inp.get("cwd") or payload.get("cwd") or os.getcwd()) if kind(tool) == "session" else \
        str(payload.get("cwd") or os.getcwd())
    st = settings(str(payload.get("cwd") or os.getcwd()))
    project = project_of(cwd, st)
    lim = caps(st, project)
    k = kind(tool)
    out = {"now": _iso(now), "tool": tool, "kind": k, "project": project, "caps": lim, "owner": st["owner"],
           "plugin": st["plugin"], "errors": st["errors"], "quota": quota_now(now, lim)}
    if k == "session":
        out["sessions"] = sessions_now(now, lim)
        out["brainstorm"] = is_brainstorm(inp, lim)
    if k in ("session", "workflow"):
        mem = memory_info()
        out["memory"], out["ram_available_gb"] = mem.get("committed"), mem.get("available_gb")
    q = out["quota"]
    week = q["windows"].get("week")
    out["session_hour_usd"], out["session_hour_applied"] = _session_hour(lim, q)
    if week and q["usd_per_pct"]:
        room = (100 - week["pct"]) * q["usd_per_pct"]
        out["quota_cap"] = max(0, math.floor(room / max(1e-9, lim["wave_hours"] * out["session_hour_usd"])) - 1)
    out["override"] = override_until(now)
    if k == "session" and lim["enabled"] and lim.get("wave_quota") and starts_now(inp):
        out["wave"] = wave_state(lim["wave_quota"], inp, str(payload.get("session_id") or ""), now, lim, q)
    return out


def _how_to_note() -> str:
    return ("call get_usage, then note each window it shows: brain usage quota --observe PCT --resets RESETS_AT "
            "(and --window 5h for the 5-hour one)")


def verdict(s: dict) -> tuple[str, str, str] | None:
    """(decision, check, reason) for the state ``s`` (:func:`state`): deny or ask; None to let the call through."""
    lim, q, k = s["caps"], s["quota"], s["kind"]
    if not k or not lim["enabled"]:
        return None
    what = {"session": "a new session", "agent": "a subagent", "workflow": "a workflow"}[k]
    wins = sorted(q["windows"].items(), key=lambda kv: -kv[1]["pct"])
    top = wins[0] if wins else None
    if top and top[1]["pct"] >= lim["critical"]:
        return ("deny", "critical", f"{what} refused: the {top[0]} quota is at {top[1]['pct']:.0f} % "
                f"(CRITICAL from {lim['critical']:g} %, {top[1]['how']} at {top[1]['at'][11:16]} UTC; resets "
                f"{top[1]['resets'][:16].replace('T', ' ')} UTC): finish the live work, start nothing new")
    if k in ("session", "workflow") and q["opted_in"] and lim["fresh_minutes"]:
        newest = _dt(q["newest"])
        age = (_dt(s["now"]) - newest).total_seconds() / 60 if newest else None
        if age is not None and age > lim["fresh_minutes"]:
            return ("deny", "stale", f"{what} refused until the quota is read: the newest reading is {age:.0f} min "
                    f"old (more than {lim['fresh_minutes']:g}); {_how_to_note()}, then start it again")
    mem, ram = s.get("memory"), s.get("ram_available_gb")
    which = memory_refusal(mem, ram, lim)
    if which:
        by = {"both": "both memory measures", "committed": "the committed memory",
              "available": "the available RAM"}[which]
        return ("deny", "memory", f"{what} refused by {by}: the machine is at {memory_text(mem, ram, lim)}; close "
                "or archive a session first")
    if k == "session":
        ss = s["sessions"]
        cap, why = int(lim["sessions"]), f"usage.guard.sessions {lim['sessions']:g}"
        if s.get("quota_cap") is not None and s["quota_cap"] < cap:
            cap, why = s["quota_cap"], (f"what the week's room pays for: {100 - q['windows']['week']['pct']:.0f} % "
                                        f"left, {lim['wave_hours']:g} h at "
                                        f"${s.get('session_hour_usd') or lim['session_hour_usd']:g} per "
                                        "session-hour" + (" measured" if s.get("session_hour_applied") else "")
                                        + ", the master's share kept")
        if ss["running"] >= cap:
            return ("deny", "sessions", f"{what} refused: {ss['running']} session(s) running in parallel, the cap is "
                    f"{cap} ({why}); finish or archive one first")
        if s["brainstorm"] and ss["brainstorms"] >= lim["brainstorms"]:
            names = ", ".join(t for t in ss["brainstorm_titles"][:4] if t)
            return ("deny", "brainstorms", f"a new brainstorm refused: {ss['brainstorms']} brainstorm(s) open on this "
                    f"machine ({names or 'not named'}), the cap is {lim['brainstorms']:g}"
                    + (f" for {s['project']}" if s["project"] else "") + "; finish or archive one first")
        v = wave_verdict(s.get("wave"))
        if v:
            return v
    if top and top[1]["pct"] >= lim["warn"]:
        return ("ask", "warn", f"{what}: the {top[0]} quota is at {top[1]['pct']:.0f} % (WARN from "
                f"{lim['warn']:g} %, CRITICAL from {lim['critical']:g} %); start it anyway?")
    return None


def wave_verdict(w: dict | None) -> tuple[str, str, str] | None:
    """The wave quota gate's answer (:func:`wave_state`): deny a stream past max_streams, ask past ask_over_pct at the
    reset; None to let it through (and when the gate is off or could not read what it needs)."""
    if not w:
        return None
    ss = w["streams"]
    if w["max_streams"] and ss.get("n") is not None and ss["n"] >= w["max_streams"]:
        names = ", ".join(ss["names"][:4])
        return ("deny", "streams", f"a new stream refused: this session already has {ss['n']} live stream(s) "
                f"({names or 'not named'}), the cap is {w['max_streams']} (usage.guard.wave_quota.max_streams: "
                "the streams of one master, their reviews included); wait until one has reported and is archived")
    p, pct = w["projection"], w["item_pct"]
    if w["ask_over_pct"] and p is not None and p["at_reset"] + (pct or 0.0) > w["ask_over_pct"]:
        cost = (f" plus this stream's {pct:.1f} % (${w['usd']:.2f}, {w['usd_basis']})" if pct is not None
                else f" ({w['usd_basis']} for this stream)")
        return ("ask", "wave_quota", f"a new stream: the week's forecast at its reset "
                f"{p['resets'][:16].replace('T', ' ')} UTC is {p['at_reset']:.0f} % ({p['now_pct']:.0f} % now + "
                f"{p['pct_h']:.2f} %/h x {p['hours_left']:.1f} h){cost}: {p['at_reset'] + (pct or 0.0):.0f} %, over "
                f"{w['ask_over_pct']:g} % (usage.guard.wave_quota.ask_over_pct); start it anyway?")
    return None


def override_hint(owner: str) -> str:
    return (f"Override ({owner} only): brain usage allow --hours {ALLOW_HOURS:g} in their own terminal (refused to "
            "sessions), or BRAIN_GUARD_ALLOW=usage in Claude Code's environment")


def _record(payload: dict, check: str, decision: str, reason: str) -> None:
    d = paths.ledger_dir()
    if os.environ.get("BRAIN_CAPTURE", "1") == "0" or not d.is_dir():
        return
    at = _iso(_now())
    rec = {"at": at, "event": "guard", "guard": GUARD, "check": check, "decision": decision, "reason": reason,
           "tool": payload.get("tool_name"), "session_id": payload.get("session_id"),
           "tool_use_id": payload.get("tool_use_id"), "cwd": payload.get("cwd")}
    timing.append(d / f"guards-{at[:7]}.jsonl", rec)  # the guards ledger's lock (brain.timing)


def _note_start(payload: dict, s: dict) -> None:
    """A start let through, noted so the next start counts it before the app shows it: a brainstorm (not a proposal's
    start: its title is not in the call), and a stream while the wave quota gate is on (``stream``)."""
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    brainstorm = bool(s.get("brainstorm") and inp.get("initiation") in ("user_asked", None)
                      and not inp.get("proposal_id"))
    stream = bool((s.get("wave") or {}).get("max_streams"))
    if not brainstorm and not stream:
        return
    f = paths.brain_home() / "usage" / "starts.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    stateio.rotate_log(f, keep=stateio.LOG_RETENTION["starts"])
    rec = {"at": s["now"], "brainstorm": brainstorm, "title": str(inp.get("title") or ""), "project": s["project"],
           "by": payload.get("session_id")}
    if stream:
        rec["stream"] = True
    timing.append(f, rec)


def master_note(session: str) -> str:
    """The master's watch at a start_session call (wi-brain-master-watch, ST-3, ST-4): past 80 % of its budget, the
    reminder that a master starts no new child; '' below it. It never refuses: no guard blocks start_session."""
    from . import budget
    m = budget.master_of(session)
    if not m or m.get("pct", 0) < 80:
        return ""
    return (f"Master's watch (ST-3): this master is at {m['pct']:.0f} % of its budget with {m.get('live', 0)} live "
            f"child(ren): past 80 % a master starts no new child; it hands over to a fresh master and drains its own. "
            "You decide; the call goes on (ST-4).")


def decide(payload: dict, now: datetime | None = None) -> dict | None:
    """The hook's output for ``payload`` (hookSpecificOutput with deny or ask), else None; records what it decided."""
    if not kind(payload.get("tool_name") or ""):
        return None
    s = state(payload, now)
    v = verdict(s)
    if v and (s["override"] or _env_allowed()):
        _record(payload, v[1], "overridden", v[2])
        v = None
    if s["kind"] == "session":
        from . import budget
        budget.expire(str(payload.get("session_id") or ""))   # the budget watch checks at the next call: a master
    if v is None:
        if s["kind"] == "session":
            _note_start(payload, s)
            notes = [f"Wave quota gate (usage.guard.wave_quota): {n}; the start goes through unchecked by it."
                     for n in (s.get("wave") or {}).get("notes") or []]
            note = master_note(str(payload.get("session_id") or ""))
            notes += [note] if note else []   # ST-4: a reminder with the call, never a refusal
            if notes:
                return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "\n".join(notes)}}
        return None
    decision, check, reason = v
    _record(payload, check, "denied" if decision == "deny" else "asked", reason)
    text = f"{s['plugin']} usage guard: {reason}."
    if decision == "deny":
        text += f" {override_hint(s['owner'])}."
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                   "permissionDecisionReason": text}}


def main(stdin=None, stdout=None) -> int:
    try:
        payload = midsession.read_payload(stdin)   # UTF-8 bytes, whatever the console's codepage
        out = decide(payload)
        if out:
            (stdout or sys.stdout).write(json.dumps(out) + "\n")
    except Exception as exc:   # never break the session
        try:
            from .capture import _log_error
            _log_error("governor", exc)
        except Exception:
            pass
    return 0


# --- brain usage guard -------------------------------------------------------------------------------------------

def report(cwd: str, now: datetime | None = None) -> dict:
    """``brain usage guard``: what each tool would get now, from the same state the hook reads."""
    now = now or _now()
    out = {}
    from . import sessions  # the session ids from the environment
    me = sessions.here()
    master = me["host_id"] or me["session"]
    for tool, inp in (("mcp__ccd_session__start_session", {"title": "a session"}),
                      ("mcp__ccd_session__start_session", {"title": "Brainstorm"}), ("Agent", {}), ("Workflow", {})):
        s = state({"tool_name": tool, "tool_input": inp, "cwd": cwd, "session_id": master}, now)
        v = verdict(s)
        name = "brainstorm" if inp.get("title") == "Brainstorm" else kind(tool)
        out[name] = {"decision": v[0] if v else "allow", "check": v[1] if v else "", "reason": v[2] if v else ""}
        out.setdefault("state", s)
    wq = out["state"]["caps"].get("wave_quota")
    out["waves"] = wave_room(cwd, master, [None] * (int(wq["max_streams"]) or 10), now) if wq else None
    return out


def _session_lines(s: dict, lim: dict, q: dict) -> list[str]:
    """``brain usage guard``'s sessions line (and what the week's room pays for) and its session-hour line."""
    ss = s.get("sessions") or {}
    sessions = (f"  sessions  {ss.get('running', 0)} running, {ss.get('brainstorms', 0)} brainstorm(s) open "
                f"(from {ss.get('source', '-')})"
                + (f"; the week's room pays for {s['quota_cap']} at ${s['session_hour_usd']:g} per session-hour"
                   + (" measured" if s.get("session_hour_applied") else "") if s.get("quota_cap") is not None else ""))
    measured = q.get("session_hour_usd")
    how = ("" if not measured else ", applied" if s.get("session_hour_applied") else
           ", not applied (not above the configured)" if lim["session_hour_measured"] else
           ", not applied (usage.guard.session_hour_measured false)")
    hour = (f"  session-h ${lim['session_hour_usd']:g} configured; measured "
            + (f"${measured:g}" if measured else "none") + how)
    return [sessions, hour]


def render(rep: dict) -> list[str]:
    s = rep["state"]
    lim, q = s["caps"], s["quota"]
    out = [f"usage guard ({'on' if lim['enabled'] else 'off'}; project {s['project'] or '-'}): warn {lim['warn']:g} %, "
           f"critical {lim['critical']:g} %, sessions {lim['sessions']:g}, brainstorms {lim['brainstorms']:g}, "
           f"memory {lim['memory']:g} % committed" + (f" or under {lim['memory_available_gb']:g} GB of RAM"
                                              if lim["memory_available_gb"] else "") + f", fresh {lim['fresh_minutes']:g} min"]
    for w, v in q["windows"].items():
        out.append(f"  {w:<9} {v['pct']:.0f} % ({v['how']} at {v['at'][11:16]} UTC, resets "
                   f"{v['resets'][:16].replace('T', ' ')} UTC)")
    if not q["windows"]:
        out.append(f"  quota     no reading in force; {_how_to_note()}")
    out.append(f"  newest    {q['newest'] or 'none'}" + ("" if q["opted_in"] else " (not checked: no reading in 7 d)"))
    out += _session_lines(s, lim, q)
    out.append(f"  memory    {memory_text(s.get('memory'), s.get('ram_available_gb'), lim)}")
    wq, w = lim.get("wave_quota"), rep.get("waves")
    out.append(f"  waves     ask over {wq['ask_over_pct']:g} % at the reset, {wq['max_streams']} stream(s) at most a "
               f"master; fit now {w['line']}" if wq and w else
               "  waves     off (usage.guard.wave_quota not set)" if not wq else "  waves     off (the governor off)")
    ov = s.get("override")
    out.append(f"  override  until {ov['until']}" + (f" ({ov['reason']})" if ov.get("reason") else "") if ov
               else "  override  none")
    for name in ("session", "brainstorm", "agent", "workflow"):
        r = rep[name]
        out.append(f"  {name:<10} {r['decision']}" + (f" ({r['check']}): {r['reason']}" if r["check"] else ""))
    out += [f"  error     {e}" for e in s["errors"]]
    return out
