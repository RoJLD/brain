"""``brain usage --kind``: the usage counters of every kind of tooling, keyed by a stable tool id (wi-brain-rule-usage;
spec 2026-11-01 context engine §12, spec 2026-11-03 session telemetry §2.3, spec 2026-11-03 external kits §2.1,
spec 2026-11-06 tooling scopes §4.4). Zero token, read-only.

What serves daily, and what never does: per tool, its calls, the sessions and the projects that used it, the token
cost where it can be attributed, and the last day it served; a tool with an inventory that served no session for
``UNUSED_DAYS`` days is marked « retire or merge » (less context injected, less code to keep).

The kinds and their sources (brain.toolids gives each its id). The transcripts are the first source (the token
ledger's rows, brain.usage: ``tools``, ``commands``, and since its scanner 4 ``tooling`` and ``refused``); the
OpenTelemetry export (brain.otel, when the collector runs) and the guards ledger add what the transcripts lack:

  skill      a Skill call, a slash command, a Read of its SKILL.md or an Agent's prompt naming it (``via``); the cost of
             the turns it drove; inventory: the skills a session in the project gets (brain.lint.sources: the owner's
             marketplace's enabled plugins, the user's and the project's);
  rule       a Rule node a session cites (``cited``: its id in the model's text or a tool call's input), an instruction
             file it loads (``loaded``: CLAUDE.md, the memory index, a rules file, with its size) or reads (``read``);
             a ``rule-...`` id no Rule node of the scope's graphs has is not counted; inventory: the active Rule nodes
             and the project's instruction files;
  command    a brain command (``brain <command> [<subcommand>]``, never its arguments) a session ran in a shell, mapped
             to the CLI registry's units (brain.adoption); the share of its message's cost; inventory: the registry;
             a unit a hook, another command or a schedule runs (its module's ``RUNS_VIA``), or that the engine's exec
             ledger saw run in the last ``UNUSED_DAYS`` days on this machine, is not marked;
  script     any other program and subcommand of a shell call (``git push``, ``python -m pytest``), never marked;
  mcp, tool  the MCP tools (``mcp__<server>__<tool>``) and Claude Code's own tools: calls, the share of their
             messages' cost, failures, the size of their results; with the export, their durations (p50, p90) and the
             calls a hook or a rule rejected (``tool_decision``); MCP tools seen before and silent are marked;
  hook       a hook's runs (``<event>:<matcher>``): from the transcripts (the hooks that write output, are cancelled or
             fail; the context they inject), the export's ``hook_execution_complete`` (every run, with its duration)
             when it covers the session: the larger count per session, never both added;
  guard      the refusals by guard: the guards ledger (``<BRAIN_HOME>/ledger/guards-*.jsonl``, decision ``denied``)
             joined to the transcripts' refused calls by tool use id, so a refusal is counted once; a refusal only the
             transcript holds gets the guard its words name (brain.toolids.refusal_guard); never marked (a guard that
             refuses nothing still guards);
  plugin     the sum of its skills and its servers' MCP tools (a hook cannot be traced to its plugin);
  scheduled  the schedules declared for this machine (brain.schedule) and the runs of their brain command in the
             engine's exec ledger (any caller), their last run.

Scope: a session counts for its project (brain.cost's placement); the inventory is the projects' in scope, so one
project's counts never reach another's. The engine's exec ledger is the machine's: it only spares a brain command or a
schedule the mark.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from . import paths, projects, toolids, usage

UNUSED_DAYS = 30
MARK = "retire or merge"
CHARS_PER_TOKEN = 4   # a context's size in tokens, estimated (brain digest's rule)
TOP = 10
MARKED = ("skill", "rule", "command", "mcp", "hook", "plugin", "scheduled")   # the kinds whose silence is marked
TITLES = {"skill": "Skills", "rule": "Rules", "command": "Brain commands", "script": "Scripts and programs",
          "mcp": "MCP tools", "tool": "Claude Code tools", "hook": "Hooks", "guard": "Guard refusals",
          "plugin": "Plugins", "scheduled": "Scheduled tasks"}
COUNTERS = ("calls", "cost", "chars", "fails", "loaded", "cited", "read", "call", "agent", "slash", "runs", "ms",
            "timeouts")


class Acc:
    """One tool's counters over the window, and its last day of use over all the history in scope."""
    __slots__ = ("vals", "sessions", "projects", "last", "otel_ms", "rejects")

    def __init__(self) -> None:
        self.vals: Counter = Counter()
        self.sessions: set[str] = set()
        self.projects: set[str] = set()
        self.last = ""
        self.otel_ms: list[float] = []
        self.rejects: Counter = Counter()


def _day(r: dict) -> str:
    return str(r.get("end") or r.get("start") or "")[:10]


def _brain_unit(word: str, known: dict, alias: dict) -> str:
    """A ``brain <command> <sub>`` word as the registry's unit, else its family run without a subcommand
    (``brain alerts --all``: ``brain alerts``), '' when the registry has neither; without a registry the word."""
    if not known:
        return word
    w = word.split()
    for unit in (" ".join(w[:3]), " ".join(w[:2])):
        unit = alias.get(unit, unit)
        if unit in known:
            return unit
    family = alias.get(" ".join(w[:2]), " ".join(w[:2]))
    return family if any(u.startswith(family + " ") for u in known) else ""


def row_tools(r: dict, known: dict | None = None, alias: dict | None = None,
              rules: set[str] | None = None) -> list[tuple[str, str, dict]]:
    """(kind, tool id, counters) of one ledger row, guards apart (:func:`guard_counts`). A row scanned before
    ``tooling`` (its transcript gone) gives its skills and brain commands from ``skills`` and ``commands``."""
    known, alias = known or {}, alias or {}
    out = _tools_and_scripts(r)
    t = r.get("tooling")
    out += _counted(t, known, alias, rules) if isinstance(t, dict) else _older(r, known, alias)
    out += [("plugin", p, {"calls": vals.get("calls") or 0, "cost": vals.get("cost") or 0.0})
            for kind, tid, vals in list(out) if (p := toolids.plugin_of_tool(kind, tid))]
    return out


def _calls(v: dict, *more: str) -> dict:
    return {"calls": v.get("calls") or 0, "cost": v.get("cost") or 0.0, "fails": v.get("fails") or 0,
            **{k: v.get(k) or 0 for k in more}}


def _is_brain(name: str) -> bool:
    return name == "brain" or name.startswith(("brain ", "python -m brain"))


def _tools_and_scripts(r: dict) -> list[tuple[str, str, dict]]:
    """Claude Code's tools and the MCP tools (``tools``), the programs other than brain (``commands``)."""
    out = [("mcp" if name.startswith("mcp__") else "tool", name, {**_calls(v), "chars": v.get("result_chars") or 0})
           for name, v in (r.get("tools") or {}).items() if name != "(text)" and v.get("calls")]
    return out + [("script", name, _calls(v)) for name, v in (r.get("commands") or {}).items() if not _is_brain(name)]


def _counted(t: dict, known: dict, alias: dict, rules: set[str] | None) -> list[tuple[str, str, dict]]:
    """A row's ``tooling``: its brain commands as the registry's units, its cited ``rule-...`` ids that are Rule
    nodes (all of them when the scope's graphs hold none)."""
    out = []
    for kind in ("skill", "rule", "command", "hook"):
        for tid, v in (t.get(kind) or {}).items():
            if kind == "command":
                tid = _brain_unit(tid, known, alias)
            elif kind == "rule" and tid.startswith("rule-") and rules is not None and tid not in rules:
                continue
            if tid:
                out.append((kind, tid, {k: v[k] for k in COUNTERS if k in v}))
    return out


def _older(r: dict, known: dict, alias: dict) -> list[tuple[str, str, dict]]:
    """A row scanned before ``tooling`` (its transcript gone): its skills and brain commands as the ledger kept
    them."""
    out = [("skill", sid, {"calls": v.get("calls") or 0, "cost": v.get("cost") or 0.0})
           for name, v in (r.get("skills") or {}).items() if (sid := toolids.slash_skill(name)) and v.get("calls")]
    for name, v in (r.get("commands") or {}).items():
        unit = _brain_unit("brain " + name.split("brain ", 1)[1], known, alias) if _is_brain(name) and " " in name \
            else ""
        if unit:
            out.append(("command", unit, _calls(v)))
    return out


# --- the guards ledger ---

def guard_records(folder: Path | None = None) -> dict[str, list[dict]]:
    """{session id: its refusals} from the guards ledger (decision ``denied``); a line that is not JSON skipped."""
    d = folder or paths.ledger_dir()
    out: dict[str, list[dict]] = defaultdict(list)
    for f in sorted(d.glob("guards-*.jsonl")) if d.is_dir() else []:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("decision") == "denied" and rec.get("session_id"):
                out[str(rec["session_id"])].append(rec)
    return out


def guard_counts(r: dict, ledger: list[dict], misses: Counter) -> Counter:
    """A session's refusals by guard: the ledger's and the transcript's joined by tool use id (each counted once,
    the ledger's guard first); ``misses`` counts how the two sources differ (the replay)."""
    seen: dict[str, str] = {}
    out: Counter = Counter()
    for rec in ledger:
        tuid = str(rec.get("tool_use_id") or "")
        out[str(rec.get("guard") or "guard")] += 1
        if tuid:
            seen[tuid] = str(rec.get("guard") or "")
    refused = r.get("refused") or {}
    for tuid, guard in refused.items():
        if tuid in seen:
            misses["matched"] += 1
            if seen[tuid] != guard:
                misses["words_wrong"] += 1
            continue
        out[guard] += 1
        misses["transcript_only"] += 1
    if isinstance(r.get("tooling"), dict):   # a row scanned before ``refused`` has none to join
        misses["ledger_only"] += sum(1 for t in seen if t not in refused) + sum(1 for rec in ledger
                                                                                  if not rec.get("tool_use_id"))
    return out


# --- the OpenTelemetry export ---

def otel_by_session(records: Iterable, sessions: set[str]) -> dict[str, dict]:
    """{session: {"hooks": {hook id: [ms...]}, "tools": {(kind, id): [ms...]}, "rejects": {(kind, id): {source: n}},
    "results": Counter((kind, id))}} for the sessions in scope."""
    out: dict[str, dict] = {}
    for rec in records:
        sid = rec.session
        if sid not in sessions:
            continue
        s = out.setdefault(sid, {"hooks": defaultdict(list), "tools": defaultdict(list),
                                 "rejects": defaultdict(Counter), "results": Counter()})
        if rec.event == "hook_execution_complete":
            ms = rec.num("total_duration_ms")
            s["hooks"][toolids.hook_id(rec.text("hook_name"))].append(ms if ms is not None else -1.0)
        elif rec.event in ("tool_result", "tool_decision"):
            name = rec.text("tool_name")
            key = (("mcp", toolids.mcp_id(rec.text("mcp_server.name"), rec.text("mcp_tool.name")))
                   if name == "mcp_tool" else ("tool", name))
            if not key[1]:
                continue
            if rec.event == "tool_result":
                s["results"][key] += 1
                ms = rec.num("duration_ms")
                if ms is not None:
                    s["tools"][key].append(ms)
            elif rec.text("decision") == "reject":
                s["rejects"][key][rec.text("source") or "?"] += 1
    return out


def _otel(where: Path | None, since: str, sessions: set[str]) -> tuple[dict, dict]:
    from . import otel
    folder = where or otel.folder()
    if not folder.is_dir():
        return {}, {"read": False, "folder": str(folder)}
    stats = otel.Stats()
    t0 = datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp() if since else None
    got = otel_by_session(otel.records(folder, since=t0, signals=("logs",), stats=stats), sessions)
    return got, {"read": True, "records": stats.records, "bad_lines": stats.bad, "sessions": len(got)}


# --- inventory ---

def inventory(projs: list[projects.Project], registry: dict | None = None) -> dict[str, dict[str, set[str]]]:
    """{kind: {tool id: the projects it is the inventory of}} for the projects in scope: their skills and instruction
    files (brain.lint.sources), their active Rule nodes and their schedules for this machine (the brain commands, the
    CLI registry's, are added by :func:`report`)."""
    from . import lint
    out: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    brain = lint._brain(projs)
    for p in projs:
        try:
            srcs = lint.sources(p, brain)
        except (OSError, ValueError):
            srcs = []
        for src in srcs:
            if src.kind == "skill" and toolids.skill_of_path(src.rel):
                out["skill"][toolids.skill_of_path(src.rel)].add(p.name)
            elif src.kind in ("claude-md", "memory"):
                out["rule"][toolids.rule_file(str(src.path), str(p.root))].add(p.name)
        for rid in _rule_nodes(p, active=True):
            out["rule"][rid].add(p.name)
    for name, project in _schedules(projs, registry):
        out["scheduled"][name].add(project)
    return out


def _rule_nodes(p: projects.Project, active: bool = False) -> list[str]:
    """The ids of a project's Rule nodes (``active``: those not retired)."""
    from . import resume
    out = []
    for store in p.stores if p.root.is_dir() else []:
        try:
            nodes = resume.Store.load(store).of_type("Rule")
        except (OSError, ValueError):
            continue
        out += [str(n["id"]) for n in nodes if not active or str(n.get("status") or "active") == "active"]
    return out


def rule_ids_of(projs: list[projects.Project]) -> set[str]:
    return {rid for p in projs for rid in _rule_nodes(p)}


def _schedules(projs: list[projects.Project], registry: dict | None) -> list[tuple[str, str, list[str]]]:
    """(name, project, command) of the schedules of the projects in scope declared for this machine."""
    from . import schedule
    names = {p.name for p in projs}
    try:
        decl = schedule.declared(registry or {p.name: p for p in projs})
        here = schedule.machine()
    except (OSError, ValueError):
        return []
    return [(s.name, s.project, s.command) for s in decl if s.project in names and s.here(here)]


def registry_units() -> tuple[dict, dict, dict]:
    """(the CLI's units, their aliases, how a unit is reached without a session: RUNS_VIA)."""
    from . import adoption, cli
    known, alias = adoption.units(cli.build_parser())
    return known, alias, adoption.runs_via()


def engine_runs(since: datetime, until: datetime) -> list[tuple[str, str]]:
    """The engine's exec ledger on this machine: (task, UTC day) per run in [since, until); a task is
    ``brain <command> [<sub>]`` or ``hook <name>``."""
    from . import perf
    lo, hi = since.strftime("%Y-%m-%d"), until.strftime("%Y-%m-%d")
    out = []
    for f in perf.files(None, since, engine=True):
        if "-bash-" in f.name:   # the hooks' bash fast paths: no brain command there
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if '"brain ' not in line:   # a hook's run: read no further
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            day = str(ev.get("end") or ev.get("at") or "")[:10] if isinstance(ev, dict) else ""
            if day and lo <= day <= hi and isinstance(ev.get("task"), str):
                out.append((ev["task"], day))
    return out


def schedule_units(projs: list[projects.Project], registry: dict | None) -> dict[str, str]:
    """{schedule name: the task the engine's exec ledger names its runs by (``brain <command> [<subcommand>]``)} for
    the schedules of the projects in scope declared for this machine."""
    out = {}
    for name, _, command in _schedules(projs, registry):
        words = toolids.brain_command("brain " + " ".join(command))
        out[name] = words[0] if words else ""
    return out


# --- the report ---

def _q(xs: list[float]) -> dict:
    xs = sorted(x for x in xs if x >= 0)
    if not xs:
        return {}
    qs = statistics.quantiles(xs, n=10, method="inclusive") if len(xs) > 1 else [xs[0]] * 9
    return {"n": len(xs), "p50": round(statistics.median(xs), 1), "p90": round(qs[8], 1)}


def report(led, projs: list[projects.Project], since: str, until: str = "", kind: str = "all", *,
           registry: dict | None = None, otel_dir: Path | None = None, guards_dir: Path | None = None,
           now: datetime | None = None, units: tuple | None = None, inv: dict | None = None,
           runs: list[tuple[str, str]] | None = None) -> dict:
    """The counters of ``kind`` (``all``: every kind) over [since, until) for the ledger's rows (already scoped to
    the projects), the unused marking over the ``UNUSED_DAYS`` days before ``until`` (else now). ``units``,
    ``inv`` and ``runs`` (the registry, the inventory, the engine's runs) are read when not given."""
    ref = _ref(until, now)
    cutoff = (ref - timedelta(days=UNUSED_DAYS)).strftime("%Y-%m-%d")
    kinds = toolids.KINDS if kind == "all" else (kind,)
    known, alias, via = units or registry_units()
    window = {r["session_id"]: r for r in led.rows if usage.in_window(r, since, until)}
    misses: Counter = Counter()
    gl = guard_records(guards_dir) if "guard" in kinds else {}
    accs = _from_rows(led.rows, kinds, set(window), (known, alias, rule_ids_of(projs) or None), gl, misses)
    otel_info: dict = {"read": False}
    if {"hook", "tool", "mcp"} & set(kinds):
        got, otel_info = _otel(otel_dir, since, set(window))
        _add_otel(accs, got, window, kinds, misses)
    inv = _with_commands(inv if inv is not None else inventory(projs, registry), known if "command" in kinds else {},
                         projs)
    runs = _engine(kinds, runs, since, ref)
    recent = Counter(task for task, day in runs if day >= cutoff)   # the machine's, over the UNUSED_DAYS days
    if "scheduled" in kinds:
        _add_scheduled(accs, schedule_units(projs, registry), runs, inv, since, until)
    rows = _rows(accs, kinds, inv, (cutoff, via, recent))
    return {"since": since, "until": until, "kind": kind, "sessions": len(window), "unused_days": UNUSED_DAYS,
            "cutoff": cutoff, "mark": MARK, "rows": rows, "misses": dict(misses),
            "sources": {"transcripts": len(window), "otel": otel_info,
                        "guards_ledger": sum(len(v) for v in gl.values())}}


def _with_commands(inv: dict, known: dict, projs: list[projects.Project]) -> dict:
    """The inventory with the CLI registry's units (every project's brain commands)."""
    for unit in known:
        inv.setdefault("command", {}).setdefault(unit, set()).update(p.name for p in projs)
    return inv


def _ref(until: str, now: datetime | None) -> datetime:
    """The day the unused marking counts back from: ``until``, else now."""
    if until:
        return datetime.fromisoformat(until).replace(tzinfo=timezone.utc)
    return now or datetime.now(timezone.utc)


def _rows(accs: dict, kinds, inv: dict, mark: tuple) -> list[dict]:
    """The report's rows: every tool counted, and those of the inventory of a marked kind; per kind, the used first,
    the most called first."""
    out = []
    for k in kinds:
        ids = {tid for (kk, tid) in accs if kk == k}
        if k in MARKED:
            ids |= set(inv.get(k, {}))
        out += [_row(k, tid, accs.get((k, tid)) or Acc(), inv, *mark) for tid in ids]
    return sorted(out, key=lambda x: (toolids.KINDS.index(x["kind"]), bool(x["mark"]), -x["calls"], x["id"]))


def _engine(kinds, runs: list | None, since: str, ref: datetime) -> list[tuple[str, str]]:
    """The engine's runs the brain commands' marking and the schedules read (none for the other kinds)."""
    if runs is not None or not {"scheduled", "command"} & set(kinds):
        return runs or []
    start = datetime.fromisoformat(since).replace(tzinfo=timezone.utc) if since else ref
    return engine_runs(min(start, ref - timedelta(days=UNUSED_DAYS)), ref)


def _from_rows(rows: list[dict], kinds, in_ids: set[str], ctx: tuple, gl: dict, misses: Counter) -> dict:
    """The rows' counters of the window's sessions, and every row's last use (the history in scope)."""
    known, alias, rules = ctx
    accs: dict[tuple[str, str], Acc] = defaultdict(Acc)
    for r in rows:
        inside = r["session_id"] in in_ids
        tools = row_tools(r, known, alias, rules)
        if "guard" in kinds:
            tools += [("guard", g, {"calls": n}) for g, n in
                      guard_counts(r, gl.get(r["session_id"], []), misses if inside else Counter()).items()]
        for k, tid, vals in tools:
            if k in kinds and (vals.get("calls") or vals.get("loaded") or vals.get("cited")):
                _add(accs[(k, tid)], r, vals if inside else None)
    return accs


def _add(a: Acc, r: dict, vals: dict | None) -> None:
    a.last = max(a.last, _day(r))
    if vals is not None:
        a.vals.update({k: v for k, v in vals.items() if v})
        a.sessions.add(r["session_id"])
        a.projects.add(r["project"])


def _add_otel(accs: dict, got: dict, by_sid: dict, kinds, misses: Counter) -> None:
    """The export's hook runs (the larger of its count and the transcript's per session, never both added), its
    durations and rejected calls; ``misses`` compares its counts with the transcript's (the replay)."""
    for sid, s in got.items():
        row = by_sid[sid]
        for hid, mss in s["hooks"].items() if "hook" in kinds else ():
            had = ((row.get("tooling") or {}).get("hook") or {}).get(hid, {}).get("calls") or 0
            extra = max(0, len(mss) - had)
            _add(accs[("hook", hid)], row, {"calls": extra})
            accs[("hook", hid)].otel_ms += mss
            misses["hook_runs_otel_only"] += extra
        for key, mss in s["tools"].items():
            if key[0] in kinds:
                accs[key].otel_ms += mss
        for key, src in s["rejects"].items():
            if key[0] in kinds:
                accs[key].rejects.update(src)
        for key, n in s["results"].items():
            had = ((row.get("tools") or {}).get(key[1]) or {}).get("calls") or 0
            misses[f"{key[0]}_calls_transcript_minus_otel"] += had - n


def _add_scheduled(accs: dict, units: dict[str, str], runs: list[tuple[str, str]], inv: dict, since: str,
                   until: str) -> None:
    """Each schedule's runs in the window (the engine's runs of its command, any caller) and its last run."""
    for name, unit in units.items():
        a = accs[("scheduled", name)]
        mine = [day for task, day in runs if unit and task == unit]
        a.vals["calls"] += sum(1 for day in mine if day >= (since or "") and (not until or day < until))
        a.projects |= set(inv.get("scheduled", {}).get(name, set()))
        a.last = max([a.last, *mine])


def _row(k: str, tid: str, a: Acc, inv: dict, cutoff: str, via: dict, runs: Counter) -> dict:
    v = a.vals
    row = {"kind": k, "id": tid, "calls": int(v.get("calls", 0)), "sessions": len(a.sessions),
           "projects": sorted(a.projects or inv.get(k, {}).get(tid, set())), "cost": round(v.get("cost", 0.0), 4),
           "fails": int(v.get("fails", 0)), "last_used": a.last}
    row.update(_extras(a))
    silent = k in MARKED and (not a.last or a.last < cutoff)
    if silent and k == "command" and (tid in via or _ran(tid, runs)):
        silent = False   # a hook, a command or a schedule runs it, or it ran on this machine outside any session
        row["reached"] = via.get(tid) or "the exec ledger"
    row["mark"] = MARK if silent else ""
    return row


def _extras(a: Acc) -> dict:
    """What a tool has besides its calls: its tokens (from the characters it read or injected), its uses by form,
    its durations, its rejected calls."""
    v = a.vals
    out = {key: int(v[key]) for key in ("loaded", "cited", "read", "call", "agent", "slash", "timeouts") if v.get(key)}
    if v.get("chars"):
        out["tokens"] = int(v["chars"] // CHARS_PER_TOKEN)
    if v.get("runs") and v.get("ms"):
        out["ms_mean"] = round(v["ms"] / v["runs"], 1)
    if _q(a.otel_ms):
        out["ms"] = _q(a.otel_ms)
    if a.rejects:
        out["rejects"] = dict(a.rejects)
    return out


def _ran(unit: str, runs: Counter) -> int:
    """The engine's runs of a unit, else of its family when the ledger names a run without its subcommand
    (brain.adoption.ran_count)."""
    w = unit.split()
    return int(runs.get(unit, 0)) or (int(runs.get(" ".join(w[:2]), 0)) if len(w) > 2 else 0)


# --- rendering ---

def _fmt_row(r: dict) -> str:
    parts = [f"{r['calls']:>6}", f"{r['sessions']:>4}", f"{len(r['projects']):>3}",
             usage.usd(r["cost"]) if r["cost"] else "      -"]
    extra = [f"~{usage.ktok(r['tokens'])} tok"] if r.get("tokens") else []
    if r.get("ms") or r.get("ms_mean"):
        extra.append(f"p50 {r['ms']['p50']:g} ms p90 {r['ms']['p90']:g} ms" if r.get("ms")
                     else f"mean {r['ms_mean']:g} ms")
    if r.get("fails"):
        extra.append(f"{r['fails']} failed")
    if r.get("rejects"):
        extra.append("rejected " + ", ".join(f"{n} by {s}" for s, n in sorted(r["rejects"].items())))
    extra += [f"{key} {r[key]}" for key in ("loaded", "cited", "read", "call", "slash", "agent") if r.get(key)]
    mark = f"  « {r['mark']} »" if r["mark"] else ""
    tail = f"  ({'; '.join(extra)})" if extra else ""
    return f"  {r['id'][:48]:<48} {' '.join(parts)}  last {r['last_used'] or 'never'}{mark}{tail}"


def _block(k: str, rows: list[dict], rep: dict, top: int) -> list[str]:
    """One kind's table: the used tools, the most called first, then the names of those to retire or merge."""
    used = [r for r in rows if not r["mark"]]
    unused = [r for r in rows if r["mark"]]
    lines = ["", f"{TITLES[k]} ({len(used)} used" + (f", {len(unused)} to {rep['mark']}" if unused else "") + ")",
             f"  {'id':<48} {'calls':>6} {'sess':>4} {'prj':>3}    cost"]
    lines += [_fmt_row(r) for r in (used[:top] if top else used)]
    if top and len(used) > top:
        lines.append(f"  ... {len(used) - top} more (--top 0: all)")
    if unused:
        names = ", ".join(r["id"] for r in (unused[:top] if top else unused))
        more = f" and {len(unused) - top} more" if top and len(unused) > top else ""
        lines.append(f"  « {rep['mark']} », unused since {rep['cutoff']}: {names}{more}")
    return lines


def render(rep: dict, top: int = TOP) -> list[str]:
    win = f"{rep['since'] or 'the start'} to {rep['until'] or 'now'}"
    o = rep["sources"]["otel"]
    otel = (f"the OpenTelemetry export ({o['records']} records, {o['sessions']} session(s))" if o.get("read")
            else "no OpenTelemetry export")
    lines = [f"brain usage --kind {rep['kind']}: {rep['sessions']} session(s) from {win}; unused since "
             f"{rep['cutoff']} ({rep['unused_days']} days) marked « {rep['mark']} »",
             f"  sources: the transcripts (token ledger), {otel}, the guards ledger "
             f"({rep['sources']['guards_ledger']} refusals)"]
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rep["rows"]:
        by[r["kind"]].append(r)
    for k in toolids.KINDS:
        if by.get(k):
            lines += _block(k, by[k], rep, top)
    if rep["misses"]:
        lines += ["", "Sources compared (the replay): "
                  + ", ".join(f"{k} {v}" for k, v in sorted(rep["misses"].items()))]
    return lines
