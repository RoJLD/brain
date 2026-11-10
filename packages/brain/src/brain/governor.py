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
  through is noted in ``usage/starts.jsonl``, so the next start counts it before its first turn ends.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import midsession, paths

GUARD = "usage"
DEFAULTS = {"enabled": True, "warn": 80.0, "critical": 95.0, "sessions": 8, "brainstorms": 2, "memory": 97.0,
            "memory_available_gb": 0.0, "wave_hours": 4.0, "session_hour_usd": 14.0, "session_hour_measured": False,
            "fresh_minutes": 60, "live_minutes": 30,
            "brainstorm_hours": 12, "brainstorm_title": r"^\W*brainstorm\b"}
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


def quota_now(now: datetime, lim: dict) -> dict:
    """The windows in force, {window: {pct, at, how}} (how: read, the reading as noted; forecast, the last brain
    usage quota's percent now; plus the week's last pace up to fresh_minutes past it), the newest reading's time,
    whether the machine notes readings, and the $ per % of the week."""
    home = paths.brain_home() / "usage"
    readings = []
    for line in _tail_lines(home / "quota.jsonl"):
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
    if isinstance(conv.get("usd_per_pct"), (int, float)) and conv["usd_per_pct"] > 0:
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
    for line in _tail_lines(paths.brain_home() / "usage" / "starts.jsonl", 16384):
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
    if top and top[1]["pct"] >= lim["warn"]:
        return ("ask", "warn", f"{what}: the {top[0]} quota is at {top[1]['pct']:.0f} % (WARN from "
                f"{lim['warn']:g} %, CRITICAL from {lim['critical']:g} %); start it anyway?")
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
    with open(d / f"guards-{at[:7]}.jsonl", "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")


def _note_start(payload: dict, s: dict) -> None:
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if not s.get("brainstorm") or inp.get("initiation") not in ("user_asked", None) or inp.get("proposal_id"):
        return
    f = paths.brain_home() / "usage" / "starts.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    rec = {"at": s["now"], "brainstorm": True, "title": str(inp.get("title") or ""), "project": s["project"],
           "by": payload.get("session_id")}
    with open(f, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


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
            note = master_note(str(payload.get("session_id") or ""))
            if note:   # ST-4: a reminder with the call, never a refusal
                return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": note}}
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
    for tool, inp in (("mcp__ccd_session__start_session", {"title": "a session"}),
                      ("mcp__ccd_session__start_session", {"title": "Brainstorm"}), ("Agent", {}), ("Workflow", {})):
        s = state({"tool_name": tool, "tool_input": inp, "cwd": cwd}, now)
        v = verdict(s)
        name = "brainstorm" if inp.get("title") == "Brainstorm" else kind(tool)
        out[name] = {"decision": v[0] if v else "allow", "check": v[1] if v else "", "reason": v[2] if v else ""}
        out.setdefault("state", s)
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
    ov = s.get("override")
    out.append(f"  override  until {ov['until']}" + (f" ({ov['reason']})" if ov.get("reason") else "") if ov
               else "  override  none")
    for name in ("session", "brainstorm", "agent", "workflow"):
        r = rep[name]
        out.append(f"  {name:<10} {r['decision']}" + (f" ({r['check']}): {r['reason']}" if r["check"] else ""))
    out += [f"  error     {e}" for e in s["errors"]]
    return out
