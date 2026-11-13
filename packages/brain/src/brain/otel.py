"""Claude Code's OpenTelemetry export, read from the sovereign collector's files (wi-brain-otel-telemetry; spec
2026-11-01 context engine §10 and §12, spec 2026-11-03 session telemetry §3.6). Standard library only, read-only, zero
token.

The collector of the sovereign stack (``compose/sovereign/otelcol.yaml``) writes what Claude Code exports as OTLP JSON
lines: ``metrics.jsonl`` and ``logs.jsonl`` under ``<BRAIN_HOME>/stacks/sovereign/data/otel-collector`` (its placement
data home), and rotates them into ``metrics-<time>.jsonl`` and ``logs-<time>.jsonl`` backups (``.gz`` read too).
Each line is one export batch: resources, scopes, then data points or log records.

:func:`records` reads them all, oldest file first, into :class:`Record`: one per metric data point or event, its
attributes over its resource's, values decoded (an ``intValue`` arrives as a JSON string), and never an attribute
of :data:`PRIVATE`, whatever the collector kept (files written before its processors dropped them included). A
cumulative sum is turned into increments per series, so a metric's ``value`` is always what that interval added. A
line that is not JSON (garbage, a truncated last line while the collector writes) is counted in :class:`Stats` and
skipped. It is the reusable part: the summary below and other readers (the rule and skill usage counters) iterate it.

:func:`summary` aggregates them: per UTC day, session and model, the tokens by type and the cost (the
``claude_code.token.usage`` and ``claude_code.cost.usage`` metrics), the API requests, errors and retries (the
``api_request`` and ``api_error`` events, a retry being an ``attempt`` above 1); the tool decisions by decision and
source; the tool results, their failures and error classes; the hooks' durations (``hook_execution_complete``,
p50 and p90 per hook). :func:`status` says whether the export is on (config.json ``adapters.claude.telemetry``,
Claude Code's user settings), whether the collector's health endpoint answers (bounded: it never hangs) and how old
each signal's last record is: a collector that runs with no source is the failure it exists to catch.
"""

from __future__ import annotations

import gzip
import json
import re
import socket
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from . import paths

SIGNALS = ("metrics", "logs")
DAYS = 7
TOP = 10
STALE_HOURS = 24.0
HEALTH_URL = "http://127.0.0.1:13133/"   # the collector's health_check extension (compose/sovereign)
HEALTH_TIMEOUT = 1.0
TAIL_BYTES = 4 * 1024 * 1024   # how much of a file's end status reads for its last record (a batch line is ~60 KB)
PREFIX = "claude_code."
# Never in a Record, whatever the files hold: the account (ST-8), the operating system's user name, the text of a
# prompt, a response, a tool's parameters or an error (ST-7: a failure's class only). The collector drops them too.
PRIVATE = frozenset({"user.email", "user.account_uuid", "user.account_id", "process.owner", "prompt", "prompt_text",
                     "response", "tool_parameters", "error"})
TOKEN_TYPES = ("input", "output", "cacheRead", "cacheCreation")
_NAME = re.compile(r"^[\w.:/-]{1,120}$")
_CUMULATIVE = 2   # OTLP AggregationTemporality


def folder() -> Path:
    """The collector's files: ``<BRAIN_HOME>/stacks/sovereign/data/otel-collector`` (the classes' ``collector``)."""
    return paths.brain_home() / "stacks" / "sovereign" / "data" / "otel-collector"


def files(where: Path, signal: str) -> list[Path]:
    """A signal's files in ``where``, oldest first: the rotated backups (``<signal>-*.jsonl``, ``.gz`` too) by
    modification time, then the current ``<signal>.jsonl``."""
    if not where.is_dir():
        return []
    current = where / f"{signal}.jsonl"
    backups = [f for f in where.glob(f"{signal}-*.jsonl*") if f.is_file() and f.name.endswith((".jsonl", ".jsonl.gz"))]
    backups.sort(key=lambda f: (_mtime(f), f.name))
    return backups + ([current] if current.is_file() else [])


def _mtime(f: Path) -> float:
    try:
        return f.stat().st_mtime
    except OSError:
        return 0.0


@dataclass(frozen=True)
class Record:
    """One metric data point (``signal`` metric) or one event (``signal`` event) of Claude Code's export."""
    signal: str            # "metric" or "event"
    name: str              # claude_code.token.usage, claude_code.api_request...
    at: float              # UTC seconds since the epoch (0.0: the record carries no time)
    value: float | None    # a metric's increment over its interval; None for an event
    attrs: dict            # its attributes over its resource's, decoded; never a key of PRIVATE
    scope: str = ""        # the instrumentation scope (com.anthropic.claude_code)

    @property
    def session(self) -> str:
        return str(self.attrs.get("session.id") or "")

    @property
    def day(self) -> str:
        return datetime.fromtimestamp(self.at, timezone.utc).strftime("%Y-%m-%d") if self.at else ""

    @property
    def event(self) -> str:
        """The name without ``claude_code.``: api_request, tool_result..."""
        return self.name[len(PREFIX):] if self.name.startswith(PREFIX) else self.name

    def num(self, key: str) -> float | None:
        """An attribute as a number (Claude Code sends many as strings: total_duration_ms, success counts)."""
        return _num(self.attrs.get(key))

    def flag(self, key: str) -> bool | None:
        v = self.attrs.get(key)
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower() if v is not None else ""
        return True if s in ("true", "1") else False if s in ("false", "0") else None

    def text(self, key: str) -> str:
        v = self.attrs.get(key)
        return "" if v is None else str(v)


@dataclass
class Stats:
    """What a read went through: files, lines, lines that were not a JSON object (skipped), records, data points
    of a kind not read (a histogram)."""
    files: int = 0
    lines: int = 0
    bad: int = 0
    records: int = 0
    skipped: int = 0
    first: float = 0.0
    last: float = 0.0

    def count(self, r: Record) -> None:
        self.records += 1
        if r.at:
            self.first = min(self.first, r.at) if self.first else r.at
            self.last = max(self.last, r.at)


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip()) if v is not None and str(v).strip() else None
    except ValueError:
        return None


def _list(x) -> list:
    return x if isinstance(x, list) else []


def _dict(x) -> dict:
    return x if isinstance(x, dict) else {}


def decode(v):
    """An OTLP JSON AnyValue as a Python value (an intValue arrives as a string; a value of no known kind: None)."""
    v = _dict(v)
    if "stringValue" in v:
        return str(v["stringValue"])
    if "intValue" in v:
        try:
            return int(v["intValue"])
        except (TypeError, ValueError):
            return None
    if "doubleValue" in v:
        return _num(v["doubleValue"])
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "arrayValue" in v:
        return [decode(x) for x in _list(_dict(v["arrayValue"]).get("values"))]
    if "kvlistValue" in v:
        return attributes(_dict(v["kvlistValue"]).get("values"))
    return None


# The names a tool's parameters carry that are kept, as the collector's transform/tool-names keeps them before it
# drops the parameters: so files written before it read the same.
TOOL_NAMES = {"mcp_server_name": "mcp_server.name", "mcp_tool_name": "mcp_tool.name", "skill_name": "skill.name"}


def attributes(items) -> dict:
    """A list of OTLP key-values as a dict, without the keys of PRIVATE (the names of :data:`TOOL_NAMES` taken from
    a tool's parameters first, a short name each; nothing else of them)."""
    out, names = {}, {}
    for a in _list(items):
        key = _dict(a).get("key")
        if not isinstance(key, str):
            continue
        if key == "tool_parameters":
            names = _tool_names(decode(a.get("value")))
        elif key not in PRIVATE:
            out[key] = decode(a.get("value"))
    for key, value in names.items():
        out.setdefault(key, value)
    return out


def _tool_names(params) -> dict:
    try:
        doc = json.loads(params) if isinstance(params, str) else None
    except ValueError:
        return {}
    if not isinstance(doc, dict):
        return {}
    return {TOOL_NAMES[k]: v for k, v in doc.items()
            if k in TOOL_NAMES and isinstance(v, str) and _NAME.match(v)}


def _nanos(*values) -> float:
    """The first non-zero OTLP time (nanoseconds, a string or a number) as UTC seconds; 0.0 when none."""
    for v in values:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n / 1e9
    return 0.0


def _iso(v) -> float:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() if v else 0.0
    except ValueError:
        return 0.0


def parse(line: str, cumulative: dict | None = None, stats: Stats | None = None) -> list[Record] | None:
    """The records of one collector line; None when it is not a JSON object (garbage, a truncated line).
    ``cumulative`` keeps each cumulative series' last value across lines, to turn it into increments."""
    try:
        doc = json.loads(line)
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    out: list[Record] = []
    last = cumulative if cumulative is not None else {}
    for rm in _list(doc.get("resourceMetrics")):
        res = attributes(_dict(_dict(rm).get("resource")).get("attributes"))
        for sm in _list(_dict(rm).get("scopeMetrics")):
            scope = str(_dict(_dict(sm).get("scope")).get("name") or "")
            for m in _list(_dict(sm).get("metrics")):
                out.extend(_metric(_dict(m), res, scope, last, stats))
    for rl in _list(doc.get("resourceLogs")):
        res = attributes(_dict(_dict(rl).get("resource")).get("attributes"))
        for sl in _list(_dict(rl).get("scopeLogs")):
            scope = str(_dict(_dict(sl).get("scope")).get("name") or "")
            for lr in _list(_dict(sl).get("logRecords")):
                rec = _event(_dict(lr), res, scope)
                if rec is not None:
                    out.append(rec)
    return out


def _metric(m: dict, res: dict, scope: str, last: dict, stats: Stats | None) -> list[Record]:
    name = m.get("name")
    if not isinstance(name, str) or not _NAME.match(name):
        return []
    out = []
    for kind in ("sum", "gauge"):
        data = _dict(m.get(kind))
        cumulative = kind == "sum" and data.get("aggregationTemporality") == _CUMULATIVE
        for dp in _list(data.get("dataPoints")):
            dp = _dict(dp)
            value = _num(dp["asDouble"]) if "asDouble" in dp else _num(dp.get("asInt"))
            if value is None:
                continue
            attrs = {**res, **attributes(dp.get("attributes"))}
            if cumulative:   # an increment per series: the value minus the series' last one (a reset starts over)
                key = (name, tuple(sorted((k, repr(v)) for k, v in attrs.items())), str(dp.get("startTimeUnixNano")))
                prev = last.get(key)
                last[key] = value
                value = value - prev if prev is not None and value >= prev else value
            out.append(Record("metric", name, _nanos(dp.get("timeUnixNano")), value, attrs, scope))
    for kind in ("histogram", "exponentialHistogram", "summary"):
        if stats is not None and kind in m:
            stats.skipped += len(_list(_dict(m[kind]).get("dataPoints")))
    return out


def _event(lr: dict, res: dict, scope: str) -> Record | None:
    attrs = {**res, **attributes(lr.get("attributes"))}
    body = decode(lr.get("body"))
    if isinstance(body, str) and _NAME.match(body):   # Claude Code's body is the event's name, never free text here
        name = body
    elif isinstance(attrs.get("event.name"), str) and _NAME.match(attrs["event.name"]):
        name = PREFIX + attrs["event.name"]
    else:
        return None
    at = _nanos(lr.get("timeUnixNano"), lr.get("observedTimeUnixNano")) or _iso(attrs.get("event.timestamp"))
    return Record("event", name, at, None, attrs, scope)


def _lines(f: Path) -> Iterator[str]:
    """A file's lines, decoded leniently; a gzip backup cut short ends where it is readable."""
    try:
        if f.name.endswith(".gz"):
            with gzip.open(f, "rt", encoding="utf-8", errors="replace") as fh:
                try:
                    yield from fh
                except (EOFError, OSError, gzip.BadGzipFile):
                    return
        else:
            with f.open(encoding="utf-8", errors="replace") as fh:
                yield from fh
    except OSError:
        return


def records(where: Path | None = None, since: float | None = None, signals: Iterable[str] = SIGNALS,
            stats: Stats | None = None) -> Iterator[Record]:
    """Every record of the collector's files in ``where`` (default :func:`folder`), oldest file first; with
    ``since`` (UTC seconds), only those at or after it (a backup last written before it is not opened). A missing
    folder yields nothing; :func:`status` says why."""
    where = where or folder()
    st = stats if stats is not None else Stats()
    for signal in signals:
        cumulative: dict = {}   # per signal: a cumulative series runs on from a backup into the current file
        for f in files(where, signal):
            if since is None or f.name == f"{signal}.jsonl" or _mtime(f) >= since:
                yield from _file_records(f, since, cumulative, st)


def _file_records(f: Path, since: float | None, cumulative: dict, st: Stats) -> Iterator[Record]:
    st.files += 1
    for line in _lines(f):
        if not line.strip():
            continue
        st.lines += 1
        recs = parse(line, cumulative, st)
        if recs is None:
            st.bad += 1
            continue
        for r in recs:
            if since is None or r.at >= since:
                st.count(r)
                yield r


# --- the summary ------------------------------------------------------------------------------------------------

def _pcts(xs: list[float]) -> dict:
    """n, p50, p90 and max of ``xs`` (linear interpolation between ranks)."""
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return {"n": 0, "p50": None, "p90": None, "max": None}

    def q(p: float) -> float:
        k = (len(xs) - 1) * p
        lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
        return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)

    return {"n": len(xs), "p50": q(0.5), "p90": q(0.9), "max": round(xs[-1], 1)}


def _row() -> dict:
    return {"tokens": dict.fromkeys(TOKEN_TYPES, 0), "cost_usd": 0.0, "api_requests": 0, "api_errors": 0,
            "retries": 0, "sessions": set()}


@dataclass
class Summary:
    """What :func:`summary` returns; :meth:`as_dict` is the --json document."""
    folder: str
    since: str | None
    session: str | None
    stats: Stats
    by_day: dict = field(default_factory=lambda: defaultdict(_row))
    by_session: dict = field(default_factory=lambda: defaultdict(_row))
    by_model: dict = field(default_factory=lambda: defaultdict(_row))
    decisions: Counter = field(default_factory=Counter)        # (decision, source) -> count
    rejected: Counter = field(default_factory=Counter)         # tool -> rejects
    tools: dict = field(default_factory=lambda: defaultdict(lambda: {"runs": 0, "failures": 0,
                                                                      "error_types": Counter(), "ms": []}))
    hooks: dict = field(default_factory=lambda: defaultdict(lambda: {"runs": 0, "blocking": 0, "errors": 0,
                                                                      "ms": []}))
    api_status: Counter = field(default_factory=Counter)       # an api_error's status_code -> count
    names: Counter = field(default_factory=Counter)            # every metric and event name -> records

    def add(self, r: Record) -> None:
        """One record: its name counted, its day's, session's and model's rows, then what ADDS says."""
        self.names[r.name] += 1
        sid, model = r.session, r.text("model")
        groups = [self.by_day[r.day or "?"], self.by_session[sid or "?"]] + ([self.by_model[model]] if model else [])
        for g in groups if sid else ():
            g["sessions"].add(sid)
        add = ADDS.get((r.signal, r.event))
        if add is not None:
            add(self, r, groups)

    def as_dict(self, top: int = 0) -> dict:
        def rows(d: dict, key: str, order=None, limit: int = 0) -> list[dict]:
            items = sorted(d.items(), key=order or (lambda kv: kv[0]))
            out = []
            for k, r in items[:limit] if limit else items:
                out.append({key: k, "tokens": r["tokens"], "tokens_total": sum(r["tokens"].values()),
                            "cost_usd": round(r["cost_usd"], 4), "api_requests": r["api_requests"],
                            "api_errors": r["api_errors"], "retries": r["retries"], "sessions": len(r["sessions"])})
            return out

        def by_cost(kv):
            return (-kv[1]["cost_usd"], kv[0])

        tools = sorted(self.tools.items(), key=lambda kv: (-kv[1]["runs"], kv[0]))
        hooks = sorted(self.hooks.items(), key=lambda kv: (-(_pcts(kv[1]["ms"])["p90"] or 0), kv[0]))
        totals = _row()
        for r in self.by_day.values():
            for t in TOKEN_TYPES:
                totals["tokens"][t] += r["tokens"][t]
            for k in ("cost_usd", "api_requests", "api_errors", "retries"):
                totals[k] += r[k]
            totals["sessions"] |= r["sessions"]
        return {
            "folder": self.folder, "since": self.since, "session": self.session,
            "read": {**asdict(self.stats), "first": _when(self.stats.first), "last": _when(self.stats.last)},
            "totals": {"tokens": totals["tokens"], "tokens_total": sum(totals["tokens"].values()),
                       "cost_usd": round(totals["cost_usd"], 4), "api_requests": totals["api_requests"],
                       "api_errors": totals["api_errors"], "retries": totals["retries"],
                       "sessions": len(totals["sessions"])},
            "by_day": rows(self.by_day, "day"),
            "by_model": rows(self.by_model, "model", by_cost),
            "by_session": rows(self.by_session, "session", by_cost, top),
            "api_error_status": dict(sorted(self.api_status.items())),
            "tool_decisions": [{"decision": d, "source": s, "count": n}
                               for (d, s), n in sorted(self.decisions.items(), key=lambda kv: (-kv[1], kv[0]))],
            "tool_rejects": dict(self.rejected.most_common()),
            "tools": [{"tool": k, "runs": v["runs"], "failures": v["failures"],
                       "error_types": dict(v["error_types"].most_common()), **_ms(v["ms"])}
                      for k, v in (tools[:top] if top else tools)],
            "hooks": [{"hook": k, "runs": v["runs"], "blocking": v["blocking"], "errors": v["errors"], **_ms(v["ms"])}
                      for k, v in (hooks[:top] if top else hooks)],
            "names": dict(sorted(self.names.items())),
        }


def _ms(xs: list[float]) -> dict:
    p = _pcts(xs)
    return {"p50_ms": p["p50"], "p90_ms": p["p90"], "max_ms": p["max"]}


def _when(t: float) -> str | None:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if t else None


def _tool_key(r: Record) -> str:
    tool = r.text("tool_name") or "?"
    server, name = r.text("mcp_server.name"), r.text("mcp_tool.name")
    if server or name:
        return f"{tool} {server or '?'}/{name or '?'}"
    skill = r.text("skill.name")
    return f"{tool} {skill}" if skill else tool


def summary(recs: Iterable[Record], where: Path | None = None, since: float | None = None,
            session: str | None = None, stats: Stats | None = None) -> Summary:
    """The aggregates of ``recs`` (Claude Code's records only: a name under ``claude_code.``); with ``session``,
    only the records of the sessions whose id starts with it."""
    s = Summary(str(where or folder()), _when(since) if since else None, session, stats or Stats())
    for r in recs:
        if r.name.startswith(PREFIX) and (not session or r.session.startswith(session)):
            s.add(r)
    return s


def _tokens(s: Summary, r: Record, groups: list[dict]) -> None:
    if r.text("type") in TOKEN_TYPES:
        for g in groups:
            g["tokens"][r.text("type")] += int(r.value or 0)


def _cost(s: Summary, r: Record, groups: list[dict]) -> None:
    for g in groups:
        g["cost_usd"] += r.value or 0.0


def _api(s: Summary, r: Record, groups: list[dict]) -> None:
    """An api_request or an api_error; a retry is an attempt above 1 (Claude Code's ``attempt``)."""
    key = "api_requests" if r.event == "api_request" else "api_errors"
    retry = (r.num("attempt") or 1) > 1
    for g in groups:
        g[key] += 1
        g["retries"] += retry
    if r.event == "api_error":
        s.api_status[r.text("status_code") or "?"] += 1


def _decision(s: Summary, r: Record, groups: list[dict]) -> None:
    s.decisions[(r.text("decision") or "?", r.text("source") or "?")] += 1
    if r.text("decision") == "reject":
        s.rejected[_tool_key(r)] += 1


def _result(s: Summary, r: Record, groups: list[dict]) -> None:
    t = s.tools[_tool_key(r)]
    t["runs"] += 1
    if r.flag("success") is False:
        t["failures"] += 1
        t["error_types"][r.text("error_type") or "?"] += 1
    if r.num("duration_ms") is not None:
        t["ms"].append(r.num("duration_ms"))


def _hook(s: Summary, r: Record, groups: list[dict]) -> None:
    h = s.hooks[r.text("hook_name") or r.text("hook_event") or "?"]
    h["runs"] += 1
    h["blocking"] += int(r.num("num_blocking") or 0)
    h["errors"] += int(r.num("num_non_blocking_error") or 0)
    if r.num("total_duration_ms") is not None:
        h["ms"].append(r.num("total_duration_ms"))


# What each record adds, by (signal, name without claude_code.); the others are only counted in ``names``.
ADDS = {("metric", "token.usage"): _tokens, ("metric", "cost.usage"): _cost, ("event", "api_request"): _api,
        ("event", "api_error"): _api, ("event", "tool_decision"): _decision, ("event", "tool_result"): _result,
        ("event", "hook_execution_complete"): _hook}


def _k(n) -> str:
    """A count, short: 950, 12.3k, 4.56M."""
    n = float(n or 0)
    return f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1e3:.1f}k" if n >= 1e4 else f"{n:,.0f}"


def _v(x) -> str:
    return "-" if x is None else f"{x:,.0f}"


COLS = (f"{'':<36} {'input':>8} {'output':>8} {'cache rd':>9} {'cache wr':>9} {'cost':>9} {'requests':>8} "
        f"{'errors':>6} {'retries':>7}")


def _table(title: str, rows: list[dict], key: str, width: int = 36) -> list[str]:
    out = ["", title, COLS] if rows else []
    for r in rows:
        t, label = r["tokens"], str(r[key])
        label = label if len(label) <= width else label[:width - 1] + "~"
        out.append(f"{label:<{width}} {_k(t['input']):>8} {_k(t['output']):>8} {_k(t['cacheRead']):>9} "
                   f"{_k(t['cacheCreation']):>9} {'$' + format(r['cost_usd'], ',.2f'):>9} "
                   f"{r['api_requests']:>8} {r['api_errors']:>6} {r['retries']:>7}")
    return out


def _pairs(d: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in d.items())


def _decision_lines(doc: dict) -> list[str]:
    if not doc["tool_decisions"]:
        return []
    out = ["", "tool decisions: " + ", ".join(f"{d['decision']}/{d['source']} {d['count']}"
                                              for d in doc["tool_decisions"])]
    return out + (["  rejected: " + _pairs(doc["tool_rejects"])] if doc["tool_rejects"] else [])


def _tool_lines(doc: dict) -> list[str]:
    head = ["", f"{'tool':<32} {'runs':>6} {'failed':>6} {'p50 ms':>8} {'p90 ms':>8}  error types"]
    return (head if doc["tools"] else []) + [
        f"{t['tool'][:32]:<32} {t['runs']:>6} {t['failures']:>6} {_v(t['p50_ms']):>8} {_v(t['p90_ms']):>8}  "
        f"{_pairs(t['error_types'])}" for t in doc["tools"]]


def _hook_lines(doc: dict) -> list[str]:
    head = ["", f"{'hook (by p90)':<32} {'runs':>6} {'p50 ms':>8} {'p90 ms':>8} {'max ms':>8} {'blocking':>8} "
                f"{'errors':>6}"]
    return (head if doc["hooks"] else []) + [
        f"{h['hook'][:32]:<32} {h['runs']:>6} {_v(h['p50_ms']):>8} {_v(h['p90_ms']):>8} {_v(h['max_ms']):>8} "
        f"{h['blocking']:>8} {h['errors']:>6}" for h in doc["hooks"]]


def render(doc: dict) -> list[str]:
    """The summary as text lines."""
    rd, tot = doc["read"], doc["totals"]
    head = (f"Claude Code's telemetry ({doc['folder']}): {rd['first'] or '-'} to {rd['last'] or '-'}, "
            f"{tot['sessions']} session(s), {rd['records']} record(s) from {rd['files']} file(s)")
    lines = [head + (f", session {doc['session']}" if doc["session"] else "")]
    if rd["bad"]:
        lines.append(f"  {rd['bad']} line(s) not read (not JSON: a truncated last line, garbage)")
    if not rd["records"]:
        since = f" since {doc['since']}" if doc["since"] else ""
        return lines + [f"  no record{since}: brain telemetry status says whether the export and the collector run"]
    lines += _table("per day (UTC)", doc["by_day"], "day") + _table("per model", doc["by_model"], "model")
    lines += _table("per session (by cost)", doc["by_session"], "session")
    if doc["api_error_status"]:
        lines.append("api errors by status: " + _pairs(doc["api_error_status"]))
    return lines + _decision_lines(doc) + _tool_lines(doc) + _hook_lines(doc)


# --- the status -------------------------------------------------------------------------------------------------

def last_record(f: Path) -> float:
    """The time of the newest record in the last complete JSON line of ``f`` (its end read, at most TAIL_BYTES;
    a gzip backup whole); 0.0 when none is readable."""
    try:
        if f.name.endswith(".gz"):
            lines = list(_lines(f))
        else:
            with f.open("rb") as fh:
                size = fh.seek(0, 2)
                fh.seek(max(0, size - TAIL_BYTES))
                lines = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return 0.0
    for line in reversed(lines):
        recs = parse(line) if line.strip() else None
        if recs:
            return max(r.at for r in recs)
    return 0.0


def signal_state(where: Path, signal: str) -> dict:
    """A signal's files: how many, their bytes, the last record's time (newest file first; a file just rotated may
    hold none yet)."""
    fs = files(where, signal)
    last = 0.0
    for f in reversed(fs):
        last = last_record(f)
        if last:
            break
    size = 0
    for f in fs:
        try:
            size += f.stat().st_size
        except OSError:
            pass
    return {"files": len(fs), "bytes": size, "last": last}


def probe(url: str = HEALTH_URL, timeout: float = HEALTH_TIMEOUT) -> tuple[str, str]:
    """The collector's health endpoint: (up | down | slow | garbage | unavailable, what was seen). Bounded by
    ``timeout``, no proxy (the URL is loopback)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as resp:
            body = resp.read(4096)
    except urllib.error.HTTPError as exc:
        return "unavailable", f"HTTP {exc.code}"
    except (socket.timeout, TimeoutError):
        return "slow", f"no answer within {timeout:g} s"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            return "slow", f"no answer within {timeout:g} s"
        return "down", str(exc.reason)
    except (OSError, ValueError) as exc:
        return "down", str(exc)
    try:
        doc = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        doc = None
    if not isinstance(doc, dict) or not isinstance(doc.get("status"), str):
        return "garbage", "an answer that is not the health_check extension's JSON"
    return "up", doc["status"][:80]


def export_state(cfg, settings_file: Path | None = None) -> dict:
    """Whether Claude Code's export is on: config.json ``adapters.claude.telemetry`` (what the installer writes)
    and Claude Code's user settings (what it reads), with the endpoint and the signals exported. No header is read."""
    from . import ipchealth
    t = ipchealth.telemetry(cfg)
    f = settings_file or ipchealth.claude_settings_file()
    env, readable = {}, True
    try:
        data = json.loads(f.read_text(encoding="utf-8-sig")) if f.is_file() else {}
    except (OSError, ValueError):
        data, readable = {}, False
    if isinstance(data, dict) and isinstance(data.get("env"), dict):
        env = data["env"]
    on = str(env.get(ipchealth.ENABLE_VAR, "")).strip().lower() in ("1", "true")
    exported = [s for s, var in (("metrics", "OTEL_METRICS_EXPORTER"), ("logs", "OTEL_LOGS_EXPORTER"))
                if "otlp" in str(env.get(var, "")).lower()]
    return {"config": bool(t["enabled"]), "settings": on if readable else None, "settings_file": str(f),
            "endpoint": str(env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "") or None, "signals": exported}


def status(cfg, where: Path | None = None, url: str = HEALTH_URL, timeout: float = HEALTH_TIMEOUT,
           stale_hours: float = STALE_HOURS, now: float | None = None, settings_file: Path | None = None) -> dict:
    """The export, the collector and its files, each as lines (OK, OFF, warning, FAIL); ``exit`` 1 on a FAIL.

    FAIL: the export is on and the collector does not answer; or it answers, a signal is exported and its last
    record is older than ``stale_hours`` (or there is none): the collector runs with no source. A warning: the
    collector runs while the export is off (nothing feeds it), the settings do not have what config.json asks for
    yet, or the folder is missing while the collector answers (its data in a Docker volume, not under BRAIN_HOME)."""
    where = where or folder()
    now = time.time() if now is None else now
    exp = export_state(cfg, settings_file)
    state, seen = probe(url, timeout)
    sig = {s: signal_state(where, s) for s in SIGNALS}
    on, up = bool(exp["settings"]), state == "up"
    lines = _export_lines(exp) + [_collector_line(url, state, seen, on)]
    if not where.is_dir():
        lines.append(("warning", f"no collector files in {where} (its placement data is not home: the files stay in "
                                 "its Docker volume)") if up else ("OFF", f"no collector files in {where}"))
    else:
        lines += [_signal_line(s, sig[s], up, on, s in exp["signals"], now, stale_hours) for s in SIGNALS]
    return {"export": exp, "collector": {"url": url, "state": state, "seen": seen}, "folder": str(where),
            "signals": {s: {**v, "last": _when(v["last"])} for s, v in sig.items()},
            "lines": [{"state": st, "line": ln} for st, ln in lines],
            "exit": 1 if any(st == "FAIL" for st, _ in lines) else 0}


def _export_lines(exp: dict) -> list[tuple[str, str]]:
    if exp["settings"] is None:
        return [("warning", f"Claude Code's settings {exp['settings_file']} could not be read")]
    if exp["settings"]:
        return [("OK", f"Claude Code's export: on in {exp['settings_file']} (endpoint {exp['endpoint'] or 'its default'}"
                       f", {', '.join(exp['signals']) or 'no signal'} exported)")]
    out = [("OFF", f"Claude Code's export: off in {exp['settings_file']}")]
    if exp["config"]:
        out.append(("warning", "config.json adapters.claude.telemetry asks for the export; Claude Code's settings do "
                               "not have it yet (install.ps1 -Apply adds it)"))
    return out


def _collector_line(url: str, state: str, seen: str, on: bool) -> tuple[str, str]:
    if state == "up":
        return ("OK", f"the collector answers at {url} ({seen})")
    if on:
        return ("FAIL", f"the collector does not answer at {url}: {state}, {seen} (brain up otel-collector)")
    return ("OFF", f"the collector does not answer at {url}: {state}, {seen}")


def _signal_line(signal: str, info: dict, up: bool, on: bool, wanted: bool, now: float,
                 stale_hours: float) -> tuple[str, str]:
    """A signal's line: FAIL when the collector answers, the export is on and sends it, and it has no record for
    ``stale_hours``; a warning when the collector answers with the export off and nothing recent."""
    age = (now - info["last"]) / 3600 if info["last"] else None
    what = (f"{signal}: {info['files']} file(s), {info['bytes'] / 1e6:.1f} MB, last record "
            + (f"{_when(info['last'])} ({_age(age)} ago)" if age is not None else "none"))
    stale = age is None or age > stale_hours
    if up and on and wanted and stale:
        return ("FAIL", f"{what}: nothing for more than {stale_hours:g} h while the export is on, the collector "
                        "receives nothing (its endpoint, its token: brain health ipc)")
    if up and not on and stale:
        return ("warning", f"{what}: the collector runs with no source (Claude Code's export is off)")
    return ("OK" if info["last"] else "OFF", what)


def _age(hours: float) -> str:
    return f"{hours * 60:.0f} min" if hours < 1 else f"{hours:.1f} h" if hours < 48 else f"{hours / 24:.1f} days"
