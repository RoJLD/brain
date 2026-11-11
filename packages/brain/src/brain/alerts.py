"""Project alerts live in the Brain (wi-brain-project-alerts; the owner 2026-10-30, a project's ADR #92): each project's
alerts in its section of the cockpit (``brain status --project p``, ``brain alerts [--project p | --all]``), sent
through the notification channels (brain.notify) per level. Every source is read at zero token:

  scheduler  the Windows Task Scheduler's tasks under the folders a project declares (one PowerShell call per pass):
             missed passes against the task's cadence, killed, failed, disabled, a permanent task not running, and a
             task that ran without leaving its proof in the exec ledger (silent);
  ledger     the exec events of ``brain timed`` (brain.timing) as the proof of a task's runs, for a task the
             scheduler does not run (``tasks: {name: {every, ledger}}``);
  stack      a watched stack (``watch: true``) or a stack the project names under ``alerts: stacks:`` DOWN or STALE;
  code-index a repo of the project's code index STALE, NOT INDEXED, MISSING or unreadable;
  audit      the audit debt above the counts of the project's written audit view (notes/audit.md);
  events     the alert events of the project (kind ``alert`` of ``schemas/event.schema.json``: ``brain alerts raise |
             resolve`` and :func:`emit` write them to ``$BRAIN_HOME/ledger/alert-<yyyy-mm>.jsonl``; a project's own
             folders under ``alerts: events:`` hold the same lines), folded by key, and its error events (kind
             ``error``), open until a later successful run of their task or for ERROR_HOURS;
  file       the project's own Markdown alert files (a project's ``notes/alerts.md`` until its writers move to
             events: ``## <date> — <writer>`` then ``WARN|FAIL  source:key  message`` lines; each writer's latest
             block is open, for FILE_DAYS);
  engine     the engine's own errors (brain.selftime, ``ledger/engine/error-<yyyy-mm>.jsonl``): a hook or a command
             that caught the same exception ENGINE_FAILS (3) times in the last 24 hours, at level error for a hook
             (a guard that fails lets the call through) and warn for a command; carried by the brain's own project
             (the one named brain, or whose root is the personal brain).
  session    a master past 80 % of its budget that still has live children (the budget watch's master state,
             brain.budget; ST-4): warn, error from 90 %; carried as engine is.
  probe      this machine's dependency probes (brain.depprobes, config.json ``probes``) that are not OK: key
             ``probe:<name>``, at the probe's level; carried as engine is. The pass (``brain alerts`` without
             ``--quick``) runs them; a view reads their last run.

A task alerts after MISSED (2) missed passes (the owner, 2026-10-30: a 15-minute task after 30 minutes), its own
``missed:`` otherwise: a pass is missed when no run started within the cadence plus a grace (a tenth of it, 1 to 15
minutes); one missed pass is shown at level info (late), never sent unless info is routed. The cadence is ``every:``,
else the scheduler's triggers (the shortest repetition running a day or more, else the trigger's days or weeks); a
running task is never missed. ``brain alerts --notify`` is the pass a scheduled task runs: it compares the open alerts
with the last pass (``$BRAIN_HOME/alerts/state.json``), sends each new alert, each one whose level rose and each one
whose send failed through ``brain notify`` at its level with its key, sends ``resolved`` at info for a delivered one
that closed, and appends each change to ``$BRAIN_HOME/alerts/alert-<yyyy-mm>.jsonl`` (the history, same schema).
Nothing leaves the machine without a ``notify:`` route (none until ddr-2026-11-02-ntfy-server is answered), and
``$BRAIN_NOTIFY=off`` sends nothing (the tests run so). A route whose channels all lack their variable (an unset
``$BRAIN_NTFY_TOPIC``) sends nothing either: the pass says so in one line, records ``unset``, and sends those alerts
at the first pass that finds the variable set. Each pass also records itself (``_pass`` in the state: when, where,
the unset variables): the dead-man of brain.schedule reads it, since a silent pass cannot report its own silence.
The Task Scheduler is read on Windows only: elsewhere its folders are skipped, as with ``--quick``.

The registry (projects.yaml), inline or a YAML file relative to the project's root::

  quant:
    alerts:
      scheduler: ['\\quant\\']           # Task Scheduler folders: every task under them is watched
      exits: {1: warn, 10: ok}          # what a task's exit codes mean (default: 0 ok, any other error)
      tasks:                            # per task: every (15m, 1h, 1d), missed, level, ledger, running
        quant-recorder: {running: true} # a permanent process: an alert when it is not running
        cycle: {every: 1d, ledger: 'cycle L*'}   # proven by the exec ledger only
      stacks: [gitnexus]                # stacks whose DOWN or STALE is an alert (watched ones always are)
      files: [notes/alerts.md]          # Markdown alert files, relative to the root
      events: ['E:/data/marketdata/_events']   # folders or files of alert, error and exec events (JSONL)
      levels: {code-index: info, audit: warn}  # a source's level instead of its default
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import socket
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from . import graph, notify, paths, projects, quiet, stateio, timing

LEVELS = notify.LEVELS
RANK = {lvl: i for i, lvl in enumerate(LEVELS)}
MISSED = 2            # the owner, 2026-10-30: a 15-minute task alerts after 2 missed passes (30 minutes)
GRACE_PART, GRACE_MIN, GRACE_MAX = 0.1, 60.0, 900.0  # a tenth of the cadence, 1 to 15 minutes
FILE_DAYS = 7         # a writer's latest block of a Markdown alert file stays open this long
ERROR_HOURS = 24      # an error event without a later successful run of its task
ENGINE_FAILS = 3      # the engine's errors of one task and class in ERROR_HOURS that raise an alert
MONTHS = 2            # the event files read: this month's and the one before
SHOWN = 3             # alerts named in brain status's row
SOURCES = ("scheduler", "ledger", "stack", "code-index", "audit", "events", "file", "engine", "session", "probe")
MASTER_HOURS = 6      # a master the session tree does not know: its watch state written this recently is a live one's
KEYS = {"scheduler", "exits", "tasks", "stacks", "files", "events", "levels"}
TASK_KEYS = {"every", "missed", "level", "ledger", "running"}
EXIT_LEVELS = ("ok", *LEVELS)
DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(s|m|min|h|d|w)\s*$")
UNITS = {"s": 1, "m": 60, "min": 60, "h": 3600, "d": 86400, "w": 604800}
ISO_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
TERMINATED, INTERRUPTED = 0x41306, 0xC000013A
# The Task Scheduler's own results (winerror.h, SCHED_*, as an ops error catalogue lists them): (what, level),
# None for a result that says nothing is wrong. An exit code below 0x10000 is read through ``exits:``.
RESULTS = {
    0x41300: ("ready", None), 0x41301: ("running", None), 0x41302: ("disabled", "warn"),
    0x41303: ("not run yet", None), 0x41304: ("no more runs scheduled", "warn"),
    TERMINATED: ("terminated (killed at its time limit or by hand)", "error"),
    0x8004131F: ("an instance was already running", None), 0x800710E0: ("refused: already running", None),
    0x80070420: ("already running", None), 0x800704DD: ("not logged on", "warn"),
    INTERRUPTED: ("interrupted (Ctrl+C or logoff)", "error"), 0x80070002: ("file not found", "error"),
    0x8007010B: ("invalid working directory", "error"),
}
DEFAULT_LEVEL = {"stack": {"DOWN": "error", "STALE": "warn"},
                 "code-index": {"STALE": "info", "NOT INDEXED": "info", "MISSING": "warn", "ERROR": "warn"}}
FILE_LEVEL = {"INFO": "info", "WARN": "warn", "WARNING": "warn", "FAIL": "error", "ERROR": "error",
              "CRITICAL": "critical"}
FILE_HEAD = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2})?))?\s*(?:[—–-]+\s*(.*))?$")
FILE_LINE = re.compile(r"^\s*(INFO|WARN|WARNING|FAIL|ERROR|CRITICAL)\s{2,}(\S+)\s{2,}(.+?)\s*$")
AUDIT_LINE = re.compile(r"^\*\*[^*:]+: P0 (\d+), P1 (\d+), P2 (\d+)\.\*\*\s*$", re.M)


class AlertsError(Exception):
    """A bad alerts: entry in the registry (exit code 2)."""


@dataclass
class Alert:
    project: str
    key: str           # stable within the project: task:<name>:missed, stack:<name>, freshness:returns_matic...
    level: str         # info, warn, error, critical
    source: str        # one of SOURCES
    subject: str       # the task, stack, repo or data source it is about
    message: str
    since: str = ""    # when it started, when known (UTC, ISO)
    code: int | str | None = None

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}


@dataclass
class Task:
    name: str
    every: float | None = None   # seconds
    missed: int = MISSED
    level: str = "error"
    ledger: str = ""             # fnmatch pattern on the exec events' task
    running: bool = False


@dataclass
class Config:
    project: str
    scheduler: list[str] = field(default_factory=list)
    exits: dict[int, str] = field(default_factory=dict)
    tasks: dict[str, Task] = field(default_factory=dict)
    stacks: list[str] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    events: list[Path] = field(default_factory=list)
    levels: dict[str, str] = field(default_factory=dict)


# --- time ---

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(text) -> datetime | None:
    if not isinstance(text, str) or len(text) < 10:
        return None
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")


def seconds(value) -> float:
    """15m, 1h, 1d, 2w, 90s, or a number of minutes; raises ValueError."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value) * 60
    m = DURATION.match(str(value))
    if not m or float(m.group(1)) <= 0:
        raise ValueError(f"{value!r}: a duration such as 15m, 1h, 1d, 2w")
    return float(m.group(1)) * UNITS[m.group(2)]


def every_text(s: float) -> str:
    for unit, n in (("w", 604800), ("d", 86400), ("h", 3600), ("min", 60)):
        if s >= n and s % n == 0:
            return f"{int(s // n)} {unit}"
    return f"{int(s)} s"


def iso_seconds(text) -> float | None:
    """PT15M, P1D, PT1H30M (a trigger's repetition) in seconds; None when empty or not one."""
    m = ISO_DURATION.match(str(text or ""))
    if not text or not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return float(d * 86400 + h * 3600 + mi * 60 + s)


# --- the registry entry ---

def _entry(p: projects.Project) -> dict:
    raw = p.alerts
    if raw is None:
        return {}
    if isinstance(raw, str):
        f = p.root / raw
        if not f.is_file():
            raise AlertsError(f"{p.name}: alerts file {raw} not found under {p.root}")
        raw = graph.load_yaml_file(f) or {}
    if not isinstance(raw, dict):
        raise AlertsError(f"{p.name}: alerts: must be a mapping or a YAML file")
    unknown = set(map(str, raw)) - KEYS
    if unknown:
        raise AlertsError(f"{p.name}: alerts: unknown key(s) {', '.join(sorted(unknown))} "
                          f"(known: {', '.join(sorted(KEYS))})")
    return raw


def _list(value, where: str) -> list[str]:
    value = [value] if isinstance(value, str) else value if value is not None else []
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise AlertsError(f"{where}: a list of strings")
    return list(value)


def _path(text: str, root: Path) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(text)))
    return p if p.is_absolute() else root / p


def _level(value, where: str) -> str:
    if value not in LEVELS:
        raise AlertsError(f"{where}: a level ({', '.join(LEVELS)}), got {value!r}")
    return value


def _task(project: str, name: str, conf) -> Task:
    where = f"{project}: alerts task {name!r}"
    conf = conf or {}
    if not isinstance(conf, dict):
        raise AlertsError(f"{where}: a mapping of {', '.join(sorted(TASK_KEYS))}")
    unknown = set(map(str, conf)) - TASK_KEYS
    if unknown:
        raise AlertsError(f"{where}: unknown key(s) {', '.join(sorted(unknown))} (known: {', '.join(sorted(TASK_KEYS))})")
    t = Task(str(name))
    if "every" in conf:
        try:
            t.every = seconds(conf["every"])
        except ValueError as exc:
            raise AlertsError(f"{where}: every: {exc}") from None
    if "missed" in conf:
        if not isinstance(conf["missed"], int) or isinstance(conf["missed"], bool) or conf["missed"] < 1:
            raise AlertsError(f"{where}: missed is a number of passes, 1 or more")
        t.missed = conf["missed"]
    if "level" in conf:
        t.level = _level(conf["level"], f"{where}: level")
    if "ledger" in conf:
        if not isinstance(conf["ledger"], str) or not conf["ledger"]:
            raise AlertsError(f"{where}: ledger is a pattern on the exec events' task (cycle L*)")
        t.ledger = conf["ledger"]
    if "running" in conf:
        if not isinstance(conf["running"], bool):
            raise AlertsError(f"{where}: running is true or false")
        t.running = conf["running"]
    return t


def config(p: projects.Project) -> Config:
    """The project's alerts: entry, checked; raises AlertsError."""
    e = _entry(p)
    cfg = Config(p.name)
    cfg.scheduler = _list(e.get("scheduler"), f"{p.name}: alerts scheduler")
    exits = e.get("exits") or {}
    if not isinstance(exits, dict):
        raise AlertsError(f"{p.name}: alerts exits: a mapping of exit code -> ok or a level")
    for code, what in exits.items():
        if not isinstance(code, int) or isinstance(code, bool) or what not in EXIT_LEVELS:
            raise AlertsError(f"{p.name}: alerts exits: {code!r}: {what!r} (an exit code -> one of "
                              f"{', '.join(EXIT_LEVELS)})")
        cfg.exits[code] = what
    tasks = e.get("tasks") or {}
    if not isinstance(tasks, dict):
        raise AlertsError(f"{p.name}: alerts tasks: a mapping of task name -> its settings")
    cfg.tasks = {str(n): _task(p.name, n, c) for n, c in tasks.items()}
    cfg.stacks = _list(e.get("stacks"), f"{p.name}: alerts stacks")
    cfg.files = [_path(x, p.root) for x in _list(e.get("files"), f"{p.name}: alerts files")]
    cfg.events = [_path(x, p.root) for x in _list(e.get("events"), f"{p.name}: alerts events")]
    levels = e.get("levels") or {}
    if not isinstance(levels, dict):
        raise AlertsError(f"{p.name}: alerts levels: a mapping of source -> level")
    for src, lvl in levels.items():
        if src not in SOURCES:
            raise AlertsError(f"{p.name}: alerts levels: unknown source {src!r} (sources: {', '.join(SOURCES)})")
        cfg.levels[src] = _level(lvl, f"{p.name}: alerts levels {src}")
    return cfg


def check(registry: Mapping[str, projects.Project]) -> list[str]:
    """Every project's alerts: entry checked (brain check --all)."""
    errors = []
    for p in registry.values():
        try:
            config(p)
        except AlertsError as exc:
            errors.append(str(exc))
    return errors


# --- the scheduler (Windows Task Scheduler, through PowerShell: locale-free JSON) ---

PS_QUERY = r"""
$ErrorActionPreference = 'Stop'
$out = foreach ($folder in @(FOLDERS)) {
  foreach ($t in @(Get-ScheduledTask -TaskPath $folder -ErrorAction SilentlyContinue)) {
    $i = $t | Get-ScheduledTaskInfo
    [pscustomobject]@{
      name = $t.TaskName; folder = $t.TaskPath; state = [string]$t.State
      last_run = $(if ($i.LastRunTime -and $i.LastRunTime.Year -gt 2000) { $i.LastRunTime.ToUniversalTime().ToString('o') } else { $null })
      last_result = [int64]$i.LastTaskResult
      next_run = $(if ($i.NextRunTime -and $i.NextRunTime.Year -gt 2000) { $i.NextRunTime.ToUniversalTime().ToString('o') } else { $null })
      triggers = @(foreach ($g in @($t.Triggers)) { [pscustomobject]@{
        type = $g.CimClass.CimClassName; enabled = $g.Enabled; interval = $g.Repetition.Interval
        duration = $g.Repetition.Duration; days = $g.DaysInterval; weeks = $g.WeeksInterval } })
    }
  }
}
ConvertTo-Json -InputObject @($out) -Depth 4 -Compress
"""
SCHEDULER_TIMEOUT = 60.0
OFF_WINDOWS = "the Task Scheduler is read on Windows only"


def _powershell(folders: list[str]) -> tuple[list[dict], str]:
    """Every task under ``folders``: (rows, '') or ([], why it could not be read). Replaced by a fake in the tests."""
    if os.name != "nt":
        return [], OFF_WINDOWS
    quoted = ", ".join("'" + f.replace("'", "''") + "'" for f in folders)  # a literal: -Command has no $args
    argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_QUERY.replace("FOLDERS", quoted)]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=SCHEDULER_TIMEOUT, encoding="utf-8",
                              errors="replace", stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"the scheduler could not be read: {type(exc).__name__}"
    if proc.returncode != 0:
        last = (proc.stderr.strip().splitlines() or [f"exit {proc.returncode}"])[0][:200]
        return [], f"the scheduler could not be read: {last}"
    try:
        rows = json.loads(proc.stdout or "[]")
    except ValueError:
        return [], "the scheduler's answer is not JSON"
    return ([r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []), ""


_scheduler = _powershell


def read_scheduler(cfgs: list[Config]) -> dict:
    """{folder-or-name: row} for the tasks of every project's scheduler folders, in one call; {"error": why} when the
    scheduler could not be read, {} when no project declares a folder."""
    folders = sorted({f for c in cfgs for f in c.scheduler})
    if not folders:
        return {}
    rows, why = _scheduler(folders)
    if why == OFF_WINDOWS:
        return {}  # another system: no Task Scheduler to read, as with --quick
    if why:
        return {"error": why}
    return {"rows": rows}


def _norm_folder(f: str) -> str:
    f = "\\" + f.strip("\\") + "\\" if f.strip("\\") else "\\"
    return f.lower()


def cadence(row: dict) -> float | None:
    """A scheduled task's cadence from its triggers: the shortest repetition that runs a day or more (or without end),
    else the shortest trigger period (daily, weekly); None for a task started by an event only (logon, boot)."""
    best = None
    for g in row.get("triggers") or []:
        if not isinstance(g, dict) or g.get("enabled") is False:
            continue
        kind = str(g.get("type") or "")
        period = (86400.0 * int(g.get("days") or 1) if "Daily" in kind else
                  604800.0 * int(g.get("weeks") or 1) if "Weekly" in kind else None)
        rep, dur = iso_seconds(g.get("interval")), iso_seconds(g.get("duration"))
        if rep and (dur is None or dur >= 86400):
            period = rep if period is None else min(period, rep)
        if period:
            best = period if best is None else min(best, period)
    return best


# --- the exec, error and alert events ---

def _event_files(paths_: list[Path], kinds: tuple[str, ...], now: datetime) -> list[Path]:
    """The ledger's files of these kinds for this month and the one before, then the declared files and folders."""
    out = []
    y, m = now.year, now.month
    for _ in range(MONTHS):
        out += [paths.ledger_dir() / f"{k}-{y:04d}-{m:02d}.jsonl" for k in kinds]
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    for p in paths_:
        out += sorted(p.rglob("*.jsonl")) if p.is_dir() else [p]
    seen, files = set(), []
    for f in out:
        key = os.path.normcase(str(f))
        if key not in seen and f.is_file():
            seen.add(key)
            files.append(f)
    return files


def read_events(project: str, extra: list[Path], now: datetime | None = None) -> list[dict]:
    """The project's exec, error and alert events of the ledger and of its declared files and folders, oldest first;
    a line that is not an event of the project is skipped."""
    now = now or _now()
    out = []
    for f in _event_files(extra, ("exec", "error", "alert"), now):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("project") == project and _ts(ev.get("at")):
                out.append(ev)
    out.sort(key=lambda e: _ts(e["at"]))
    return out


def _start(ev: dict) -> datetime | None:
    return _ts(ev.get("start")) or _ts(ev.get("at"))


# --- the verdicts ---

def _exit_level(code: int, exits: dict[int, str]) -> str | None:
    what = exits.get(code, "ok" if code == 0 else "error")
    return None if what == "ok" else what


def result(code, exits: dict[int, str]) -> tuple[str, str | None, bool]:
    """A scheduler result or an exit code: (what it means, its level or None, killed)."""
    try:
        code = int(code) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return "unknown result", None, False
    if code in RESULTS:
        what, lvl = RESULTS[code]
        return what, lvl, code in (TERMINATED, INTERRUPTED)
    if code < 0x10000:
        return f"exit {code}", _exit_level(code, exits), False
    return f"uncatalogued result 0x{code:08X}", "error", False


def _grace(every: float) -> float:
    return min(GRACE_MAX, max(GRACE_MIN, every * GRACE_PART))


def task_alerts(project: str, t: Task, row: dict | None, runs: list[dict], exits: dict[int, str],
                now: datetime) -> list[Alert]:
    """The alerts of one task from its scheduler row (None: not in the scheduler) and its exec events (oldest first)."""
    key, out = f"task:{t.name}", []

    def add(what: str, level: str, message: str, since: datetime | None = None, code=None, source: str = "scheduler"):
        out.append(Alert(project, f"{key}:{what}", level, source if row else "ledger", t.name, message,
                         _iso(since) if since else "", code))

    state = str((row or {}).get("state") or "")
    if row and state == "Disabled":
        add("disabled", "info", f"{t.name} is disabled in the scheduler")
        return out
    if t.running:
        if row and state != "Running":
            add("stopped", t.level, f"{t.name} is not running (scheduler state {state or 'unknown'})")
        elif not row:
            add("stopped", "warn", f"{t.name}: not in the scheduler (declared running: true)")
        return out
    sched_start = _ts((row or {}).get("last_run"))
    last_run = runs[-1] if runs else None
    run_start = _start(last_run) if last_run else None
    starts = [s for s in (sched_start, run_start) if s]
    every = t.every or (cadence(row) if row else None)
    if not starts:
        add("unproven", "warn", f"{t.name}: no run proven yet" + ("" if row or t.ledger else
                                                                  " (no scheduler task and no ledger: pattern)"))
        return out
    last = max(starts)
    if every and state != "Running":
        n = int((now - last).total_seconds() - _grace(every)) // int(every) if now > last else 0
        if n >= 1:
            lvl = t.level if n >= t.missed else "info"
            add("missed", lvl, f"{t.name}: {n} pass{'es' if n > 1 else ''} missed, every {every_text(every)}, "
                               f"last run started {_short(last)}" + ("" if n >= t.missed else f" (alert at {t.missed})"),
                last + timedelta(seconds=every))
    elif not every:
        add("unmeasured", "info", f"{t.name}: no cadence (an event trigger only): declare every:")
    # the latest run's outcome: the scheduler's when it is the latest, else the ledger's
    if sched_start and (not run_start or sched_start > run_start + timedelta(seconds=GRACE_MIN)):
        code = (row or {}).get("last_result")
        what, lvl, killed = result(code, exits)
        if lvl:
            if isinstance(code, int) and code & 0xFFFFFFFF >= 0x10000:
                code = f"0x{code & 0xFFFFFFFF:08X}"
            add("killed" if killed else "result", lvl, f"{t.name}: last run {_short(sched_start)}: {what}",
                sched_start, code)
        if t.ledger and state != "Running" and (lvl is None or lvl == "info") and what != "not run yet":
            add("silent", "warn", f"{t.name}: ran {_short(sched_start)} without its proof in the exec ledger "
                                  f"(brain timed, task {t.ledger})", sched_start, source="scheduler")
    elif last_run is not None:
        code, err = last_run.get("exit"), str(last_run.get("error") or "")
        if err == "interrupted" or code == 130 or (isinstance(code, int) and code < 0):
            add("killed", "error", f"{t.name}: last run {_short(run_start)} was {err or f'killed (exit {code})'}",
                run_start, code, source="ledger")
        elif isinstance(code, int):
            lvl = _exit_level(code, exits)
            if lvl:
                add("result", lvl, f"{t.name}: last run {_short(run_start)} exited {code}"
                                   + (f" ({err})" if err else ""), run_start, code, source="ledger")
    return out


def scheduler_alerts(cfg: Config, sched: dict, events: list[dict], now: datetime) -> list[Alert]:
    """Every task of the project's scheduler folders and every declared task."""
    if not cfg.scheduler and not cfg.tasks:
        return []
    if cfg.scheduler and "error" in sched:
        return [Alert(cfg.project, "scheduler", "warn", "scheduler", "scheduler",
                      f"not read: {sched['error']}")]
    mine = {_norm_folder(f) for f in cfg.scheduler}
    rows = {str(r.get("name")): r for r in sched.get("rows") or []
            if _norm_folder(str(r.get("folder") or "\\")) in mine and r.get("name")}
    names = sorted(set(rows) | set(cfg.tasks)) if cfg.scheduler and sched else sorted(cfg.tasks)
    out = []
    for name in names:
        t = cfg.tasks.get(name) or Task(name)
        runs = [e for e in events if e.get("kind", "exec") == "exec" and t.ledger
                and fnmatch.fnmatchcase(str(e.get("task") or ""), t.ledger)]
        runs.sort(key=lambda e: _start(e) or now)
        row = rows.get(name)
        if row is None and not t.ledger and cfg.scheduler and not sched:
            continue  # --quick: the scheduler was not read
        out += task_alerts(cfg.project, t, row, runs, cfg.exits, now)
    return out


def stack_alerts(cfg: Config, rows, watched: set[str]) -> list[Alert]:
    if not isinstance(rows, list):
        return []
    want = watched | set(cfg.stacks)
    out = []
    for r in rows:
        if r.get("name") in want and r.get("state") not in ("OK", "OFF"):  # OFF: outside the profile, by choice
            lvl = cfg.levels.get("stack") or DEFAULT_LEVEL["stack"].get(r["state"], "error")
            out.append(Alert(cfg.project, f"stack:{r['name']}", lvl, "stack", r["name"],
                             f"stack {r['name']} {r['state']}" + (f": {r['why']}" if r.get("why") else "")))
    return out


def index_alerts(cfg: Config, rows) -> list[Alert]:
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if r.get("state") != "OK":
            lvl = cfg.levels.get("code-index") or DEFAULT_LEVEL["code-index"].get(r["state"], "warn")
            out.append(Alert(cfg.project, f"code-index:{r['repo']}", lvl, "code-index", r["repo"],
                             f"code index of {r['repo']} {r['state']}" + (f": {r['why']}" if r.get("why") else "")
                             + ("" if r["state"] == "ERROR" else f" (brain index {r['repo']})")))
    return out


def audit_baseline(root: Path) -> dict | None:
    """The counts of the project's written audit view (brain audit --write), else None."""
    from .audit import VIEW
    f = root / VIEW
    try:
        m = AUDIT_LINE.search(f.read_text(encoding="utf-8"))
    except OSError:
        return None
    return {"P0": int(m.group(1)), "P1": int(m.group(2)), "P2": int(m.group(3))} if m else None


def audit_alerts(cfg: Config, measured, base: dict | None) -> list[Alert]:
    counts = (measured or {}).get("counts") if isinstance(measured, dict) else None
    if not counts or not base:
        return []
    rose = [s for s in ("P0", "P1", "P2") if counts.get(s, 0) > base[s]]
    if not rose:
        return []
    lvl = cfg.levels.get("audit") or ("error" if "P0" in rose else "warn" if "P1" in rose else "info")
    return [Alert(cfg.project, "audit:debt", lvl, "audit", "audit",
                  "audit debt rose since the written view (notes/audit.md): "
                  + ", ".join(f"{s} {base[s]} -> {counts.get(s, 0)}" for s in rose))]


def event_alerts(cfg: Config, events: list[dict], now: datetime) -> list[Alert]:
    """The open alerts among the project's alert events (the last event of a key decides) and its recent error
    events not followed by a successful run of their task."""
    last: dict[str, dict] = {}
    first: dict[str, str] = {}
    for ev in events:
        if ev.get("kind") == "alert" and ev.get("key"):
            k = str(ev["key"])
            if ev.get("state") == "resolved":
                first.pop(k, None)
            else:
                first.setdefault(k, str(ev["at"]))
            last[k] = ev
    lvl_of = lambda ev: ev.get("severity") if ev.get("severity") in LEVELS else "warn"  # noqa: E731
    out = [Alert(cfg.project, k, cfg.levels.get("events") or lvl_of(ev), "events", str(ev.get("task") or k),
                 str(ev.get("message") or ev.get("details") or k)[:500]
                 + (f" [{ev['source']}]" if ev.get("source") else ""), first.get(k, str(ev["at"])), ev.get("code"))
           for k, ev in last.items() if ev.get("state") == "open"]
    ok_after: dict[str, datetime] = {}
    for ev in events:
        if ev.get("kind", "exec") == "exec" and ev.get("exit") == 0:
            ok_after[str(ev.get("task"))] = _ts(ev["at"])
    errors: dict[str, dict] = {}
    for ev in events:
        if ev.get("kind") == "error":
            at = _ts(ev["at"])
            ok = ok_after.get(str(ev.get("task")))
            if at >= now - timedelta(hours=ERROR_HOURS) and not (ok and ok > at):
                errors[f"error:{ev.get('task')}:{ev.get('code')}"] = ev
    for k, ev in errors.items():
        out.append(Alert(cfg.project, k, cfg.levels.get("events") or lvl_of(ev), "events", str(ev.get("task")),
                         f"{ev.get('task')}: error {ev.get('code')}"
                         + (f": {ev['details']}" if isinstance(ev.get("details"), str) and ev["details"] else ""),
                         str(ev["at"]), ev.get("code")))
    return out


def engine_alerts(cfg: Config, now: datetime) -> list[Alert]:
    """The engine's tasks (a hook, a command) that caught the same exception ENGINE_FAILS times or more in the last
    ERROR_HOURS (brain.selftime's error events): key ``engine:<task>:<class>``."""
    since = now - timedelta(hours=ERROR_HOURS)
    seen: dict[tuple[str, str], list] = {}
    y, m = now.year, now.month
    for _ in range(MONTHS):
        f = paths.ledger_dir() / "engine" / f"error-{y:04d}-{m:02d}.jsonl"
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            at = _ts(ev.get("at")) if isinstance(ev, dict) and ev.get("kind") == "error" else None
            if at and since <= at <= now:
                details = ev.get("details") if isinstance(ev.get("details"), dict) else {}
                row = seen.setdefault((str(ev.get("task") or "brain"), str(ev.get("code") or "error")), [0, at, ""])
                row[0] += 1
                row[1], row[2] = min(row[1], at), details.get("where") or row[2]
    out = []
    for (task, code), (n, first, where) in sorted(seen.items()):
        if n >= ENGINE_FAILS:
            level = cfg.levels.get("engine") or ("error" if task.startswith("hook ") else "warn")
            out.append(Alert(cfg.project, f"engine:{task.replace(' ', '-')}:{code}", level, "engine", task,
                             f"{task}: {code} {n} times in {ERROR_HOURS} h" + (f" (at {where})" if where else "")
                             + "; brain perf --engine, ledger/errors.log", _iso(first), code))
    return out


def _live_now(tree, session: str, m: dict, mtime: float, floor: float) -> int:
    """The live children of the master ``session`` now: read from the session tree when it knows the master (0 once
    the master itself is archived or ended, whatever its state file's age, and 0 for the state of a transcript the
    app's master has left, e.g. after a /clear: its current transcript has its own state); else the count its last
    check kept, while that state is under MASTER_HOURS old (review of #34, finding 26).

    Assumption, not yet checked against a real /clear in the desktop app: after a /clear the app moves its file's
    ``cliSessionId`` to the new transcript (``sessions.host_for`` assumes the same). Were the app to keep the old id,
    both would go wrong: the current transcript's state has no ``host_id`` then (host_for refuses it) and counts 0, so
    the master past 80 % now raises no alert of its own; and the earlier transcript's state, whose ``host_id`` and
    session still match the app's node, keeps counting its live children: a stale alert at its pre-/clear pct until the
    master or all of its children are archived or that state is pruned (budget.KEEP_DAYS)."""
    from . import sessions

    key = tree.key_of(m.get("host_id") or "") or tree.key_of(session)
    if not key:
        return int(m.get("live") or 0) if mtime >= floor else 0
    node = tree.nodes[key]
    if not sessions.alive(node, tree.ends) or (node.get("session") or session) != session:
        return 0
    return sum(1 for k in tree.children.get(key, []) if sessions.alive(tree.nodes[k], tree.ends))


def master_alerts(cfg: Config, now: datetime) -> list[Alert]:
    """A master past 80 % of its budget that still has live children (wi-brain-master-watch, ST-4): the budget
    watch's state of each session (``<BRAIN_HOME>/budget/<session>.json``, its ``master``: its pct), its liveness and
    its live children read from the session tree now (:func:`_live_now`); key ``session:master:<id>``, warn from
    80 %, error from 90 %."""
    from . import budget, sessions

    out = []
    floor = now.timestamp() - MASTER_HOURS * 3600
    try:
        files = [(f, f.stat().st_mtime) for f in sorted(budget.state_dir().glob("*.json"))]
    except OSError:
        return out
    tree = None
    for f, mtime in files:
        m = budget.master_of(f.stem)
        if not m or m.get("pct", 0) < 80:
            continue
        if tree is None:  # read once, and only when a master is past 80 %
            starts, ends = sessions.ledger_events(now.timestamp())
            tree = sessions.Tree(sessions.app_index(), starts, None, ends)
        live = _live_now(tree, f.stem, m, mtime, floor)
        if not live:
            continue
        who = m.get("host_id") or f.stem
        level = cfg.levels.get("session") or ("error" if m["pct"] >= 90 else "warn")
        out.append(Alert(cfg.project, f"session:master:{who}", level, "session", who,
                         f"master {who} at {m['pct']:.0f} % of its budget with {live} live child(ren): it starts "
                         "no new child, hands over to a fresh master and drains (ST-3); brain sessions show " + who,
                         _iso(datetime.fromtimestamp(m.get("at") or mtime, timezone.utc))))
    return out


def probe_alerts(cfg: Config, rows) -> list[Alert]:
    """Each dependency probe that is not OK (brain.depprobes's rows): key ``probe:<name>``, at its level (or
    ``levels: {probe: ...}``), since it entered its state."""
    from . import depprobes

    if not isinstance(rows, list):
        return []
    return [Alert(cfg.project, f"probe:{r['name']}", cfg.levels.get("probe") or r.get("level") or "warn", "probe",
                  r["name"], depprobes.message(r), str(r.get("since") or ""))
            for r in rows if isinstance(r, dict) and r.get("name") and r.get("state") not in (None, "OK")]


def carries_engine(p: projects.Project) -> bool:
    """Whether ``p`` shows the engine's own alerts: it is named brain, or its root is the personal brain's."""
    from .selftime import ENGINE

    if p.name == ENGINE:
        return True
    root = paths.personal_root()
    try:
        return bool(root) and p.root.resolve() == root.resolve()
    except OSError:
        return False


def parse_file(text: str) -> list[dict]:
    """A Markdown alert file's blocks: [{date, time, writer, lines: [(level, key, message)]}], in file order."""
    blocks, cur = [], None
    for line in text.splitlines():
        h = FILE_HEAD.match(line.strip())
        if h:
            cur = {"date": h.group(1), "time": h.group(2) or "", "writer": (h.group(3) or "").strip(), "lines": []}
            blocks.append(cur)
            continue
        m = FILE_LINE.match(line)
        if m and cur is not None:
            cur["lines"].append((FILE_LEVEL[m.group(1)], m.group(2), m.group(3)))
    return blocks


def file_alerts(cfg: Config, root: Path, now: datetime) -> list[Alert]:
    """Each writer's latest block of each alert file, when it is FILE_DAYS old or less."""
    out: dict[str, Alert] = {}
    for f in cfg.files:
        try:
            blocks = parse_file(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        latest: dict[str, dict] = {}
        for b in blocks:
            if b["lines"] and (b["writer"] not in latest or b["date"] >= latest[b["writer"]]["date"]):
                latest[b["writer"]] = b
        # named with its repo's folder (demo/notes/alerts.md, hedge-fund/notes/alerts.md)
        base = Path(os.path.normpath(root.parent))
        f = Path(os.path.normpath(f))
        rel = f.relative_to(base).as_posix() if f.is_relative_to(base) else f.as_posix()
        for b in latest.values():
            day = _ts(f"{b['date']}T00:00:00Z")
            if not day or day < now - timedelta(days=FILE_DAYS):
                continue
            for lvl, k, msg in b["lines"]:
                subject = k.split(":", 1)[-1]
                out[k] = Alert(cfg.project, k, cfg.levels.get("file") or lvl, "file", subject,
                               f"{msg} ({rel}, {b['writer'] or 'no writer'} {b['date']})", f"{b['date']}T00:00:00Z")
    return list(out.values())


# --- one project ---

def _sorted(alerts: list[Alert]) -> list[Alert]:
    return sorted(alerts, key=lambda a: (-RANK[a.level], a.source, a.key))


def of_project(p: projects.Project, *, stacks_rows=None, index_rows=None, audit=None, sched: dict | None = None,
               watched: set[str] | None = None, now: datetime | None = None, probe_rows=None) -> list[Alert]:
    """The open alerts of ``p`` from what was measured (brain.status's stacks, code index and audit rows; None when
    not probed), the scheduler's rows (read_scheduler; None or {} when not read) and, for the brain's own project,
    the dependency probes' rows (None: their last run, brain.depprobes.last). Raises AlertsError."""
    now = now or _now()
    cfg = config(p)
    events = read_events(p.name, cfg.events, now)
    out = scheduler_alerts(cfg, sched or {}, events, now)
    out += stack_alerts(cfg, stacks_rows, watched or set())
    out += index_alerts(cfg, index_rows)
    out += audit_alerts(cfg, audit, audit_baseline(p.root) if audit else None)
    out += event_alerts(cfg, events, now)
    out += file_alerts(cfg, p.root, now)
    if carries_engine(p):
        out += engine_alerts(cfg, now)
        out += master_alerts(cfg, now)
        if probe_rows is None:
            from . import depprobes
            probe_rows = depprobes.last()["probes"]
        out += probe_alerts(cfg, probe_rows)
    seen, unique = set(), []
    for a in _sorted(out):
        if a.key not in seen:
            seen.add(a.key)
            unique.append(a)
    return unique


def summary(alerts: list[Alert], last_pass: str | None) -> dict:
    """What brain status shows: the counts by level and the open alerts."""
    counts = {lvl: sum(1 for a in alerts if a.level == lvl) for lvl in reversed(LEVELS)}
    return {"open": len(alerts), "counts": {k: v for k, v in counts.items() if v},
            "alerts": [a.to_json() for a in alerts], "last_pass": last_pass}


# --- every project (brain alerts) ---

def run(projs: list[projects.Project], *, quick: bool = False, root: Path | None = None) -> dict:
    """{projects: [{project, found, open, counts, alerts, last_pass} or {project, found, error}], quick}: brain
    status's probes (stacks, code index, audit; none with ``quick``), the scheduler and this machine's dependency
    probes (brain.depprobes: run and recorded when the brain's own project is in scope; their last run with
    ``quick``), read once for every project."""
    from . import depprobes, status  # here: brain.status imports this module

    if not quick and any(carries_engine(p) for p in projs):
        depprobes.run()   # recorded: the brain's own project's alerts below read this run
    stack_reg, index = status._probes(root, quick)
    sched = {} if quick else read_scheduler(status._alert_configs(projs))
    last = state_load()
    out = []
    for p in projs:
        d = {"project": p.name, "found": p.root.is_dir()}
        if d["found"]:
            measured = {}
            if not quick:
                measured["audit"] = status.audit_of(p)
                if not isinstance(stack_reg, Exception):
                    measured["stacks"] = status.stacks_of(p, stack_reg or {})
                if index and not isinstance(index, Exception) and index[0]:
                    measured["code_index"] = status.code_index_of(p, *index)
            d.update(status.alerts_of(p, measured, stack_reg, sched, last))
        out.append(d)
    return {"projects": out, "quick": quick}


def render(data: dict) -> list[str]:
    lines = []
    for d in data["projects"]:
        if not d["found"]:
            lines.append(f"{d['project']}: not found on this machine")
            continue
        if "error" in d:
            lines.append(f"{d['project']}: alerts: error: {d['error']}")
            continue
        head = f"{d['project']}: {d['open']} open" + (f" ({_counts(d['counts'])})" if d["open"] else "")
        lines.append(head + f"; last notify pass {d['last_pass'] or 'never'}"
                     + (" (--quick: scheduler, stacks, code index and audit not read)" if data.get("quick") else ""))
        for a in d["alerts"]:
            lines.append(f"  {a['level'].upper():<8} {a['key']}  {a['message']}")
        if d.get("pass"):
            lines.append(f"  pass     {d['pass']['line']}")
    if len(data["projects"]) > 1:
        n = sum(d.get("open", 0) for d in data["projects"])
        lines.append(f"all: {n} open alert(s) in {sum(1 for d in data['projects'] if d.get('open'))} of "
                     f"{len(data['projects'])} project(s)")
    return lines


def _counts(c: dict) -> str:
    return ", ".join(f"{n} {k}" for k, n in c.items())


def status_line(d: dict) -> str:
    """brain status's alerts row."""
    if "error" in d:
        return f"error: {d['error']}"
    w = d.get("pass")
    if w and w.get("silent"):
        return f"{w['line']}; " + status_line({k: v for k, v in d.items() if k != "pass"})
    if not d["open"]:
        return f"none open; last notify pass {d['last_pass'] or 'never'}" + (f"; {w['line']}" if w else "")
    named = [f"{a['key']} ({a['level']})" for a in d["alerts"][:SHOWN]]
    more = d["open"] - len(named)
    return (f"{d['open']} open: {_counts(d['counts'])}; " + ", ".join(named)
            + (f" and {more} more" if more > 0 else "") + f" (brain alerts); last notify pass {d['last_pass'] or 'never'}"
            + (f"; {w['line']}" if w else ""))


# --- raise, resolve (what a project's writers call instead of a tracked alerts.md) ---

def emit(project: str, key: str, level: str = "warn", message: str = "", *, state: str = "open", task: str = "",
         source: str = "", code: int | str | None = None, link: str = "", ledger: str | Path | None = None,
         at: datetime | None = None) -> dict:
    """Append an alert event (opened, or ``state="resolved"``) to ``$BRAIN_HOME/ledger/alert-<yyyy-mm>.jsonl`` (or
    ``ledger``), under the ledger's lock; the event. Raises ValueError when it does not follow the schema."""
    if level not in LEVELS:
        raise ValueError(f"level {level!r}: one of {', '.join(LEVELS)}")
    ev = {"v": 1, "kind": "alert", "at": timing.iso(at or _now()), "host": timing.host(), "project": project,
          "task": timing._clean(task or key, timing.TASK_MAX), "key": key, "severity": level, "state": state,
          "source": source, "message": timing._clean(message, 500) if message else "", "code": code,
          "link": link, "pid": os.getpid()}
    ev = {k: v for k, v in ev.items() if v not in (None, "")}
    timing.write_event(ev, ledger)
    return ev


# --- the notify pass ---

def state_dir() -> Path:
    return paths.brain_home() / "alerts"


STATE_V = 1   # truth-local (brain.stateio): v 1 stays unwritten, so that 0.2.5 reads every key as a project


def _state_shape(data: dict) -> str:
    bad = sorted(k for k, r in data.items() if not isinstance(r, dict))
    return f"{', '.join(bad[:3])} not an object" if bad else ""


def state(write: bool = False) -> stateio.State:
    """The alerts already sent and the last pass on this machine, under brain.stateio's policy (set aside only to
    write)."""
    return stateio.load(state_dir() / "state.json", known=STATE_V, check=_state_shape, aside=write)


def state_load() -> dict:
    return state().data


def _state_save(data: dict) -> None:
    stateio.save(state(write=True), data, write_v=False)


def _history(a: dict, project: str, state: str, now: datetime) -> dict:
    return {k: v for k, v in {
        "v": 1, "kind": "alert", "at": timing.iso(now), "host": socket.gethostname() or "unknown", "project": project,
        "task": timing._clean(a.get("subject") or a["key"], timing.TASK_MAX), "key": a["key"],
        "severity": a["level"], "state": state, "source": a.get("source") or "", "message":
        timing._clean(a.get("message") or "", 500)}.items() if v not in (None, "")}


def changes(prev: dict, alerts: list[dict]) -> tuple[list[dict], list[dict]]:
    """(the alerts to send: new, level risen or never delivered; the previous ones now closed)."""
    now_keys = {a["key"] for a in alerts}
    send = []
    for a in alerts:
        p = prev.get(a["key"])
        if p is None or RANK[a["level"]] > RANK.get(p.get("level"), -1) or p.get("sent") in ("failed", "unset"):
            send.append(a)
    closed = [{"key": k, **v} for k, v in prev.items() if k not in now_keys]
    return send, closed


def notify_pass(data: dict, registry: Mapping[str, projects.Project], *, dry_run: bool = False,
                now: datetime | None = None, env: Mapping[str, str] | None = None) -> list[str]:
    """Send the changes since the last pass through brain notify and record them (nothing written with
    ``dry_run``); the lines to print. A project whose alerts could not be read keeps its state."""
    now = now or _now()
    loaded = state(write=not dry_run)
    if not dry_run and not loaded.writable:   # sent without a record, every pass would send them again
        return [f"nothing sent: {loaded.refusal()}"]
    st = loaded.data
    lines = quiet.release(registry, now=now, dry_run=dry_run, env=env)   # the sum-up of a quiet that has ended
    unset: set[str] = set()
    for d in data["projects"]:
        if not d.get("found") or "error" in d:
            continue
        name = d["project"]
        prev = (st.get(name) or {}).get("open") or {}
        send, closed = changes(prev, d["alerts"])
        try:
            cfg = notify.config(registry[name]) if name in registry else None
        except notify.NotifyError as exc:
            cfg, why = None, str(exc)
        else:
            why = "" if cfg else "not in the registry"
        opened: dict[str, dict] = {}
        for a in d["alerts"]:
            p = prev.get(a["key"]) or {}
            opened[a["key"]] = {"level": a["level"], "since": p.get("since") or a.get("since") or _iso(now),
                                "message": a["message"], "source": a["source"], "subject": a.get("subject", ""),
                                "sent": p.get("sent", "")}
        hist = []
        for a in send:
            missing = [] if dry_run else notify.unset(cfg, a["level"], env)
            if missing:  # said once for the pass, below; sent at the first pass that finds the variable
                unset.update(missing)
                outcome = "unset"
            else:
                outcome = _send(cfg, why, name, a["level"], a["message"], a["key"], dry_run, now, env, queue=False)
                lines.append(f"{name}: {a['level']} {a['key']}: {outcome}")
            opened[a["key"]]["sent"] = outcome
            hist.append(_history(a, name, "open", now))
        for c in closed:
            missing = [] if dry_run or c.get("sent") != "delivered" else notify.unset(cfg, "info", env)
            unset.update(missing)
            outcome = ("unset" if missing else _send(cfg, why, name, "info", f"resolved: {c.get('message', '')}",
                                                     c["key"], dry_run, now, env) if c.get("sent") == "delivered"
                       else "not sent (its alert was not delivered)")
            lines.append(f"{name}: resolved {c['key']}: {outcome}")
            hist.append(_history({**c, "level": c.get("level") or "info"}, name, "resolved", now))
        if not dry_run:
            for ev in hist:
                timing.write_event(ev, state_dir())
            st[name] = {"open": opened, "last_pass": _iso(now)}
        lines.append(f"{name}: {len(d['alerts'])} open, {len(send)} new, risen or retried, {len(closed)} resolved"
                     + (" (dry run: nothing recorded)" if dry_run else ""))
    lines += notify.replay(registry, now=now, dry_run=dry_run, env=env)   # the outbox, after this pass's sends
    if unset:
        lines.append(f"nothing sent: ${', $'.join(sorted(unset))} not set (brain notify setup ntfy); the alerts wait "
                     "for the first pass that finds it")
    if not dry_run:
        from .schedule import clock
        st["_pass"] = {"at": _iso(now), "host": socket.gethostname() or "unknown", "unset": sorted(unset),
                       "clock": clock()}
        try:
            _state_save(st)
        except (stateio.StateError, OSError) as exc:   # a newer brain wrote it meanwhile: said, not a traceback
            lines.append(f"sent, but not recorded (the next pass may send again): {exc}")
    return lines


def _send(cfg, why: str, project: str, level: str, body: str, key: str, dry_run: bool, now: datetime, env,
          queue: bool = True) -> str:
    """One alert through brain notify: delivered, failed, no-route, throttled, off, dry-run, or why not sent. An
    open alert that fails is sent again by the next pass (``queue=False``); a resolved one goes to the outbox."""
    if cfg is None:
        return f"not sent: {why}"
    msg = notify.Message(project, level, body, source="alerts", key=key)
    try:
        res = notify.send(cfg, msg, dry_run=dry_run, now=now, env=env, queue=queue)
    except notify.NotifyError as exc:
        return f"not sent: {exc}"
    return res.status
