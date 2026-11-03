"""``brain perf``: the execution-time ledger read back (spec 2026-10-30 governance §3.9), at zero token, standard library
only.

It reads the exec events of ``$BRAIN_HOME/ledger/exec-<yyyy-mm>.jsonl`` from the month of ``--since``, or the JSONL
files and folders named by ``--from`` (a project's own events store, same schema: brain.timing); events of another
kind (the ops error events) are left aside, and a line that is not an exec event is skipped and counted. A run belongs
to the period by its end. Per (project, task):

- the slowest steps: runs, failed runs (exit not 0), the median, p90 and max duration of the successful runs (all runs
  when none succeeded) and the total, longest median first;
- the trends: the median of the last RECENT_DAYS (7) days against the median before, in the period, for the tasks with
  MIN_RUNS (2) successful runs on each side, largest change first; slower when the median grew RATIO times (1.5) and by
  MIN_DELTA_S (1 s) at least, faster when it shrank as much;
- the regressions after a change: the median at the task's latest version (the version of its last run) against the
  version it ran before, MIN_RUNS successful runs each, when it grew RATIO times and by MIN_DELTA_S;
- the time lost per ISO week: the time of the failed runs (they must be redone), plus, for the successful runs slower
  than RATIO times their task's median, the time over that median.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import paths
from .timing import fmt_duration

RATIO, MIN_DELTA_S, MIN_RUNS, RECENT_DAYS, SINCE_DAYS, TOP = 1.5, 1.0, 2, 7, 28, 10
TASK_WIDTH = 48


class PerfError(Exception):
    """A bad --since or --from (exit code 2)."""


@dataclass(frozen=True)
class Run:
    project: str
    task: str
    version: str
    host: str
    end: datetime
    duration: float
    exit: int | None

    @property
    def ok(self) -> bool:
        return self.exit in (0, None)


def _ts(text) -> datetime | None:
    if not isinstance(text, str) or "T" not in text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_since(text: str | None, now: datetime) -> datetime:
    """``28d``, ``4w``, a date (YYYY-MM-DD, UTC midnight) or an ISO time; default SINCE_DAYS days before ``now``."""
    if not text:
        return now - timedelta(days=SINCE_DAYS)
    m = re.fullmatch(r"\s*(\d+)\s*([dw])\s*", text)
    if m:
        return now - timedelta(days=int(m.group(1)) * (7 if m.group(2) == "w" else 1))
    dt = _ts(text) or _ts(f"{text.strip()}T00:00:00")
    if not dt:
        raise PerfError(f"--since {text!r}: expected Nd, Nw, YYYY-MM-DD or an ISO time")
    return dt


def files(sources: list[str] | None, since: datetime) -> list[Path]:
    """The JSONL files to read: --from files and folders (*.jsonl), else the ledger's exec months from ``since``'s."""
    if not sources:
        month = since.astimezone(timezone.utc).strftime("%Y-%m")
        return sorted(f for f in paths.ledger_dir().glob("exec-*.jsonl") if f.stem[5:] >= month)
    out: list[Path] = []
    for s in sources:
        p = Path(s).expanduser()
        if p.is_dir():
            out += sorted(p.glob("*.jsonl"))
        elif p.is_file():
            out.append(p)
        else:
            raise PerfError(f"--from {s}: no such file or folder")
    return out


def _run(ev) -> Run | None:
    if not isinstance(ev, dict):
        return None
    end = _ts(ev.get("end") or ev.get("at"))
    d, code, task = ev.get("duration_s"), ev.get("exit"), ev.get("task")
    if (not end or not isinstance(task, str) or not task or isinstance(d, bool) or not isinstance(d, (int, float))
            or d < 0 or (code is not None and (isinstance(code, bool) or not isinstance(code, int)))):
        return None
    return Run(str(ev.get("project") or "-"), task, str(ev.get("version") or ""), str(ev.get("host") or ""), end,
               float(d), code)


def load(sources: list[str] | None = None, since: datetime | None = None, until: datetime | None = None,
         project: str | None = None, task: str | None = None) -> tuple[list[Run], int]:
    """(the exec runs of the period, sorted by end; the number of lines skipped). ``task``: a case-blind substring."""
    now = datetime.now(timezone.utc)
    since = since or now - timedelta(days=SINCE_DAYS)
    runs, skipped = [], 0
    for f in files(sources, since):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped += 1
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(ev, dict) or ev.get("kind", "exec") != "exec":
                continue
            r = _run(ev)
            if r is None:
                skipped += 1
                continue
            if r.end < since or (until and r.end > until):
                continue
            if project and r.project != project:
                continue
            if task and task.lower() not in r.task.lower():
                continue
            runs.append(r)
    return sorted(runs, key=lambda r: r.end), skipped


def _groups(runs: list[Run]) -> dict[tuple[str, str], list[Run]]:
    out: dict[tuple[str, str], list[Run]] = {}
    for r in runs:
        out.setdefault((r.project, r.task), []).append(r)
    return out


def _p90(xs: list[float]) -> float:
    s = sorted(xs)
    return s[max(0, -(-9 * len(s) // 10) - 1)]  # nearest rank


def _durations(runs: list[Run]) -> list[float]:
    return [r.duration for r in runs if r.ok] or [r.duration for r in runs]


def slowest(runs: list[Run]) -> list[dict]:
    rows = []
    for (project, task), rs in _groups(runs).items():
        ds = _durations(rs)
        rows.append({"project": project, "task": task, "runs": len(rs), "failed": sum(not r.ok for r in rs),
                     "median_s": round(statistics.median(ds), 3), "p90_s": round(_p90(ds), 3),
                     "max_s": round(max(ds), 3), "total_s": round(sum(r.duration for r in rs), 3),
                     "last_s": round(rs[-1].duration, 3)})
    return sorted(rows, key=lambda r: (-r["median_s"], r["project"], r["task"]))


def _verdict(before: float, after: float) -> str:
    if after >= RATIO * before and after - before >= MIN_DELTA_S:
        return "slower"
    if before >= RATIO * after and before - after >= MIN_DELTA_S:
        return "faster"
    return ""


def trends(runs: list[Run], now: datetime) -> list[dict]:
    cut = now - timedelta(days=RECENT_DAYS)
    rows = []
    for (project, task), rs in _groups(runs).items():
        before = [r.duration for r in rs if r.ok and r.end < cut]
        recent = [r.duration for r in rs if r.ok and r.end >= cut]
        if len(before) < MIN_RUNS or len(recent) < MIN_RUNS:
            continue
        b, a = statistics.median(before), statistics.median(recent)
        if b <= 0:
            continue
        rows.append({"project": project, "task": task, "before_s": round(b, 3), "recent_s": round(a, 3),
                     "change": round(a / b - 1, 4), "runs_before": len(before), "runs_recent": len(recent),
                     "verdict": _verdict(b, a)})
    return sorted(rows, key=lambda r: (-r["change"], r["project"], r["task"]))


def regressions(runs: list[Run]) -> list[dict]:
    rows = []
    for (project, task), rs in _groups(runs).items():
        latest = rs[-1].version
        if not latest:
            continue
        first = next(i for i, r in enumerate(rs) if r.version == latest)
        previous = next((r.version for r in reversed(rs[:first]) if r.version and r.version != latest), "")
        if not previous:
            continue
        old = [r.duration for r in rs if r.ok and r.version == previous]
        new = [r.duration for r in rs if r.ok and r.version == latest]
        if len(old) < MIN_RUNS or len(new) < MIN_RUNS:
            continue
        b, a = statistics.median(old), statistics.median(new)
        if b > 0 and _verdict(b, a) == "slower":
            rows.append({"project": project, "task": task, "from": previous, "to": latest, "before_s": round(b, 3),
                         "after_s": round(a, 3), "change": round(a / b - 1, 4), "runs_before": len(old),
                         "runs_after": len(new), "since": next(r.end for r in rs if r.version == latest).isoformat()})
    return sorted(rows, key=lambda r: (-r["change"], r["project"], r["task"]))


def weeks(runs: list[Run]) -> list[dict]:
    base = {}
    for k, rs in _groups(runs).items():
        ok = [r.duration for r in rs if r.ok]
        if ok:
            base[k] = statistics.median(ok)
    out: dict[str, dict] = {}
    for r in runs:
        y, w, _ = r.end.isocalendar()
        row = out.setdefault(f"{y}-W{w:02d}", {"week": f"{y}-W{w:02d}", "runs": 0, "total_s": 0.0, "failed_s": 0.0,
                                               "slow_s": 0.0})
        row["runs"] += 1
        row["total_s"] += r.duration
        median = base.get((r.project, r.task))
        if not r.ok:
            row["failed_s"] += r.duration
        elif median and r.duration > RATIO * median:
            row["slow_s"] += r.duration - median
    rows = []
    for k in sorted(out):
        row = out[k]
        row["lost_s"] = row["failed_s"] + row["slow_s"]
        rows.append({k2: round(v, 3) if isinstance(v, float) else v for k2, v in row.items()})
    return rows


def report(runs: list[Run], skipped: int, since: datetime, now: datetime, project: str | None = None,
           top: int = TOP) -> dict:
    return {"since": since.isoformat(), "until": now.isoformat(), "project": project, "runs": len(runs),
            "tasks": len(_groups(runs)), "projects": sorted({r.project for r in runs}), "skipped": skipped,
            "slowest": slowest(runs)[:top or None], "trends": trends(runs, now)[:top or None],
            "regressions": regressions(runs), "weeks": weeks(runs)}


def _table(headers: list[str], rows: list[list], align: str) -> list[str]:
    cells = [[str(c) for c in row] for row in [headers, *rows]]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    return ["  " + "  ".join(c.rjust(w) if a == "r" else c.ljust(w) for c, w, a in zip(r, widths, align)).rstrip()
            for r in cells]


def _task(t: str) -> str:
    return t if len(t) <= TASK_WIDTH else t[:TASK_WIDTH - 3] + "..."


def render(rep: dict) -> list[str]:
    scope = f"project {rep['project']}" if rep["project"] else f"{len(rep['projects'])} project(s)"
    lines = [f"perf: {rep['runs']} run(s) of {rep['tasks']} task(s), {scope}, {rep['since'][:10]} to "
             f"{rep['until'][:10]}" + (f" ({rep['skipped']} line(s) skipped)" if rep["skipped"] else "")]
    lines += ["", "slowest steps (median of the successful runs)"]
    lines += _table(["project", "task", "runs", "failed", "median", "p90", "max", "total"],
                    [[r["project"], _task(r["task"]), r["runs"], r["failed"], fmt_duration(r["median_s"]),
                      fmt_duration(r["p90_s"]), fmt_duration(r["max_s"]), fmt_duration(r["total_s"])]
                     for r in rep["slowest"]], "llrrrrrr")
    lines += ["", f"trends (median of the last {RECENT_DAYS} days against before)"]
    if rep["trends"]:
        lines += _table(["project", "task", "before", "last days", "change", ""],
                        [[r["project"], _task(r["task"]), fmt_duration(r["before_s"]), fmt_duration(r["recent_s"]),
                          f"{r['change']:+.0%}", r["verdict"]] for r in rep["trends"]], "llrrrl")
    else:
        lines.append(f"  none: no task has {MIN_RUNS} successful runs both in the last {RECENT_DAYS} days and before")
    lines += ["", f"regressions after a change (median at the latest version against the one before, x{RATIO:g})"]
    if rep["regressions"]:
        lines += _table(["project", "task", "versions", "before", "after", "change"],
                        [[r["project"], _task(r["task"]), f"{r['from']} -> {r['to']}", fmt_duration(r["before_s"]),
                          fmt_duration(r["after_s"]), f"{r['change']:+.0%}"] for r in rep["regressions"]], "lllrrr")
    else:
        lines.append("  none")
    lines += ["", f"time lost per week (failed runs, and the time over the median of runs slower than x{RATIO:g})"]
    lines += _table(["week", "runs", "total", "failed", "slow", "lost"],
                    [[r["week"], r["runs"], fmt_duration(r["total_s"]), fmt_duration(r["failed_s"]),
                      fmt_duration(r["slow_s"]), fmt_duration(r["lost_s"])] for r in rep["weeks"]], "lrrrrr")
    return lines


def main(project: str | None = None, since: str | None = None, task: str | None = None, top: int = TOP,
         sources: list[str] | None = None, as_json: bool = False, out=None, now: datetime | None = None) -> int:
    out = out or sys.stdout
    now = now or datetime.now(timezone.utc)
    try:
        start = parse_since(since, now)
        runs, skipped = load(sources, start, now, project, task)
    except PerfError as exc:
        print(f"brain perf: {exc}", file=sys.stderr)
        return 2
    rep = report(runs, skipped, start, now, project, top)
    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1), file=out)
    elif not runs:
        where = ", ".join(sources) if sources else str(paths.ledger_dir())
        print(f"perf: no exec event since {start.date()} in {where}"
              + (f" for project {project}" if project else "") + (f" and task ~{task!r}" if task else "")
              + (f" ({skipped} line(s) skipped)" if skipped else "")
              + "; brain timed -- COMMAND (or brain.timing.timed) writes them", file=out)
    else:
        print("\n".join(render(rep)), file=out)
    return 0
