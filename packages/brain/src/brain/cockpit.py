"""The cockpit's panels: ``brain tui [--project p | --all]`` (wi-brain-tui-cockpit; spec 2026-10-30 §3.6 and §3.14;
Q7: a file watch with a 2 s fallback re-read). This is the data layer, the standard library and brain only:
the Textual app (``brain.tui``, the ``tui`` extra) and the text view (``brain tui --once``, and ``--plain`` or no
extra: the same text redrawn in place) both draw it.

Eight panels, each read through the function its command already uses:

  sessions    the sessions whose transcript was written in the last ``--hours`` (24): project (the folder placed as
              brain queue places it), title, branch, step n/m of its plan (brain.plan: the hook's file, else the
              plan calls of the transcript), state, model, effort, context used and its budget, output tokens and
              the cost at API prices (the SR snapshot the Stop hook writes, <BRAIN_HOME>/sessions/<id>.json, priced
              by brain.usage; the costliest first: ``--sort sessions:cost``), last write;
  queue       the owner's queue (brain.queue.collect, as brain queue calls it): decisions, actions, permissions, in
              three bands (now, this week, when you can), ranked by what each holds up (its score; brain queue
              --explain), with the recommended option and how to answer; titled with the owner's display name;
  alerts      each project's open alerts by level (brain.status.alerts_of, as brain status and brain alerts: the
              scheduler, the exec ledger, the stacks, the code index, the audit, the alert events and files);
  milestones  each pending milestone's items done out of its live items, and how many are reached (brain.status);
  frontier    the startable todo items by priority, a proposed priority marked ``?`` (brain.status.frontier), with
              the milestone each is part of (or proposed for, marked ``?``), the open items and pending milestones
              downstream of it, and the age of its idea (the date its ``idea`` prop names);
  audit       the findings by severity and repo, the first P0 and P1 ones (brain.status.audit_of, as brain audit);
  health      each stack's and code index repo's state (brain.status, as brain health and brain index), and the
              execution-time ledger's last 7 days (brain.perf: runs, failures, regressions);
  digest      the journals' last day and the records (brain.status.records_of), then the latest written digest
              (brain.digest.latest), else last week's, built offline (brain.digest.build).

A session's state, from the tail of its transcript (not a public format: a record it does not know is skipped) and
the ledger's events:

  asking   its last call is a question to the owner (AskUserQuestion), or its turn ended on a wrap-up marked blocked;
  running  its turn goes on (a tool call, a tool result or a prompt is the last record);
  stale    running, but nothing written for 15 minutes: a long command, a permission prompt, or a dead process;
  idle     its turn ended (the Stop hooks' summary, or a final answer, is the last record): it waits for a message;
  ended    the SessionEnd hook recorded its end.

Three speeds keep a refresh cheap:

  ticks   every ``--refresh`` (2 s): the sessions, each transcript's tail read again only when its size or time
          changed, so that the ages and the stale state move;
  files   queue, milestones, frontier: re-read when a file they come from changed (the graph stores, the DDRs, the
          journals, the queue's done stamps; their size and modification time, compared at each tick: a file watch
          by polling, which needs no library);
  probes  alerts, audit, health, digest, and the transcript scan for the queue's denied calls: every ``--probe`` (5 min),
          on the r key, and for each ``--once`` (``--quick``: none). What a probe measured is kept per project, so a
          scope already probed is shown again at once when the project selector comes back to it.

The view (ADR "Le cockpit : sélecteur de projet, filtres et tri", spec 2026-11-02 cockpit-ux): the sessions, the
queue and the frontier each have filters and sorts (``FILTERS``, ``SORTS``), and every table a search (each word of
it in the row, case ignored). ``shown`` applies a view to a panel's records, ``table`` and the text view draw what it
keeps. The defaults: the sessions not ended, by state; the queue by band, the owner's order, then the score; the
frontier by priority. ``HELP`` says what each panel shows, where it comes from and which command gives the detail
(the TUI's i);
``when`` shows a time in the cockpit's timezone (``TZS``: this machine's, by default, or UTC).

Read-only: nothing here writes a record or a ledger, and nothing calls a model. The one file written is the screen's
own state, ``<BRAIN_HOME>/tui.json`` (the scope, each panel's view and the settings: theme, timezone; ``save_state``),
by the interactive views. Its settings also hold, set by hand: ``lang`` (en, fr: the queue's title, « File d'Ada »;
$BRAIN_LANG wins) and ``titles`` (a free title per panel, ``{"queue": "Ma file"}``), read by every view (``title``).
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import (alerts, audit, config, decisions, digest, paths, perf, plan, projects, queue, resume, status, transcript,
               usage)

PANELS = ("sessions", "queue", "alerts", "milestones", "frontier", "audit", "health", "digest")
FILE_PANELS = {"graph": ("queue", "milestones", "frontier")}
PROBE_PANELS = ("alerts", "audit", "health", "digest")
HOURS = 24.0
STALE_S = 15 * 60
END_SLACK_S = 120  # a transcript written later than this after its session's end: resumed, not ended
TAIL_BYTES = 256 * 1024
REFRESH_S = 2.0  # Q7: the fallback re-read every 2 s
PROBE_S = 300.0
AUDIT_TOP = 12
PERF_DAYS = 7
PRIORITIES = ("P0", "P1", "P2", "P3")
STATES = ("asking", "running", "stale", "idle", "ended")
ASK_TOOLS = ("AskUserQuestion",)
WRAP_UP = "mcp__ccd_turn__wrap_up"
OUTSIDE = queue.OUTSIDE
WIDTH = 118
ALL = "all"  # the scope of every registered project
TZS = ("local", "utc")  # the cockpit's timezone: this machine's (the default), or UTC
STATE_FILE = "tui.json"
_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m|min|h)?\s*$", re.I)
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def duration(text: str) -> float:
    """``500ms``, ``2s``, ``5m`` (or ``5min``), ``1h`` or a number of seconds, as seconds."""
    m = _DURATION_RE.match(str(text))
    if not m:
        raise ValueError(f"{text!r}: a duration like 500ms, 2s, 5m or 1h")
    unit = (m.group(2) or "s").lower()
    return float(m.group(1)) * {"ms": 0.001, "s": 1, "m": 60, "min": 60, "h": 3600}[unit]


def _iso(ts: float) -> str:
    return transcript.iso(datetime.fromtimestamp(ts, timezone.utc))


# --- sessions ---

def recent_transcripts(hours: float, now: float) -> list[tuple[float, Path]]:
    """The main transcripts written in the last ``hours``, newest first (a subagent's is under
    <session>/subagents/, not one of these)."""
    root = paths.projects_dir()
    out = []
    for f in root.glob("*/*.jsonl") if root.is_dir() else []:
        try:
            m = f.stat().st_mtime
        except OSError:
            continue
        if now - m <= hours * 3600:
            out.append((m, f))
    return sorted(out, key=lambda x: -x[0])


def tail(path: Path, max_bytes: int = TAIL_BYTES) -> list[dict]:
    """The last complete records of a transcript, oldest first."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            fh.seek(max(0, size - max_bytes))
            chunk = fh.read()
    except OSError:
        return []
    lines = chunk.split(b"\n")[1 if size > max_bytes else 0:]  # the first line of a cut is partial
    out = []
    for raw in lines:
        try:
            rec = json.loads(raw) if raw.strip() else None
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _blocks(rec: dict) -> list[dict]:
    content = (rec.get("message") or {}).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _uses(rec: dict) -> list[dict]:
    return [b for b in _blocks(rec) if b.get("type") == "tool_use"]


def _prompt(rec: dict) -> bool:
    """A user record that is a prompt, not a tool result."""
    return rec.get("type") == "user" and not any(b.get("type") == "tool_result" for b in _blocks(rec))


def _blocked(records: list[dict]) -> bool:
    """The turn that ``records`` end with called the wrap-up with ``blocked``: it waits on the owner's answer."""
    for r in reversed(records):
        if _prompt(r):
            return False
        for b in _uses(r) if r.get("type") == "assistant" else []:
            if b.get("name") == WRAP_UP:
                return bool((b.get("input") or {}).get("blocked"))
    return False


def turn(records: list[dict]) -> str:
    """Where the session's turn is, from its last records: ``asking``, ``idle`` or ``active``."""
    for i in range(len(records) - 1, -1, -1):
        r = records[i]
        kind = r.get("type")
        if kind == "system":
            if r.get("subtype") == "stop_hook_summary":
                return "asking" if _blocked(records[:i]) else "idle"
            continue  # a compaction boundary, a notice: look further back
        if kind == "assistant":
            uses = _uses(r)
            if any(b.get("name") in ASK_TOOLS for b in uses):
                return "asking"
            if not uses and (r.get("message") or {}).get("stop_reason") == "end_turn":
                return "idle"
            return "active"
        if kind == "user":
            return "active"
    return "active"


def state(turn_: str, age_s: float, ended: bool = False) -> str:
    if ended:
        return "ended"
    if turn_ == "active":
        return "stale" if age_s > STALE_S else "running"
    return turn_


def meta(records: list[dict]) -> dict:
    """What the tail says of the session: folder, branch, title, model, effort, context (the last call's input)."""
    out: dict = {}
    for r in records:
        if r.get("cwd"):
            out["folder"] = r["cwd"]
        if r.get("gitBranch"):
            out["branch"] = r["gitBranch"]
        if r.get("type") == "custom-title" and r.get("customTitle"):
            out["title"] = r["customTitle"]
        msg = r.get("message") or {}
        if r.get("type") != "assistant" or msg.get("model") in (None, "<synthetic>"):
            continue
        out["model"] = msg["model"]
        if r.get("effort"):
            out["effort"] = r["effort"]
        if isinstance(msg.get("usage"), dict):
            part = transcript._usage_tokens(msg["usage"])
            out["context"] = part["input"] + part["cache_read"] + part["cache_write"]
    return out


def ended_sessions(now: float) -> dict[str, str]:
    """{session: when it ended}: the sessions whose last event in the ledger (this month's and last month's) is
    their end."""
    last: dict[str, tuple[str, str]] = {}
    d = paths.ledger_dir()
    months = {_iso(now)[:7], _iso(now - 32 * 86400)[:7]}
    for f in sorted(d / f"events-{m}.jsonl" for m in months):
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            sid = ev.get("session_id") if isinstance(ev, dict) else None
            if sid and str(ev.get("at") or "") >= last.get(sid, ("", ""))[0]:
                last[sid] = (str(ev.get("at") or ""), str(ev.get("event") or ""))
    return {sid: at for sid, (at, event) in last.items() if event == "session_end"}


def cost_of(sr: dict) -> float | None:
    """A session's cost at API prices from its SR snapshot: its tokens by model, its subagents' at its main model
    (brain.usage prices them); None without a snapshot."""
    if not sr.get("tokens_by_model"):
        return None
    sub = (sr.get("subagents") or {}).get("tokens") or {}
    extra = usage.message_cost(sub, sr.get("model") or "") if sub else 0.0
    return round(usage.tokens_cost(sr["tokens_by_model"]) + (extra or 0.0), 2)


def snapshot_of(session_id: str) -> dict:
    """The SR snapshot the Stop hook keeps (<BRAIN_HOME>/sessions/<id>.json), {} without one."""
    try:
        data = json.loads((paths.sessions_dir() / f"{session_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class Sessions:
    """The sessions panel, kept between refreshes: a transcript is read again only when it changed."""

    def __init__(self, placer, hours: float = HOURS) -> None:
        self.placer, self.hours = placer, hours
        self.replay = plan.Replay()
        self.seen: dict[str, tuple] = {}  # path -> (size, mtime_ns, turn, meta)

    def _read(self, f: Path) -> tuple[str, dict]:
        try:
            st = f.stat()
        except OSError:
            return "active", {}
        key = (st.st_size, st.st_mtime_ns)
        old = self.seen.get(str(f))
        if old and old[:2] == key:
            return old[2], old[3]
        records = tail(f)
        found = {**(old[3] if old else {}), **meta(records)}  # a tail of big tool results keeps the last known
        self.seen[str(f)] = (*key, turn(records), found)
        return self.seen[str(f)][2], found

    def rows(self, only: set[str] | None = None, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        ended = ended_sessions(now)
        recent = recent_transcripts(self.hours, now)
        keep = {str(f) for _, f in recent}  # a session out of the window is forgotten
        self.seen = {k: v for k, v in self.seen.items() if k in keep}
        self.replay.state = {k: v for k, v in self.replay.state.items() if k in keep}
        out = []
        for mtime, f in recent:
            sid = f.stem
            turn_, m = self._read(f)
            sr = snapshot_of(sid)
            folder = m.get("folder") or sr.get("folder") or ""
            project = (self.placer(folder) if folder else "") or OUTSIDE
            if only is not None and project not in only:
                continue
            hook = plan.read(sid)
            steps = hook["steps"] if hook else self.replay.steps(f)
            tokens, ctx = sr.get("tokens") or {}, sr.get("context") or {}
            age = max(0.0, now - mtime)
            out.append({"session_id": sid, "project": project, "title": m.get("title") or sr.get("title") or "",
                        "folder": folder, "branch": m.get("branch") or sr.get("branch") or "",
                        "state": state(turn_, age, ended.get(sid, "") >= _iso(mtime - END_SLACK_S)),
                        "step": plan.label(steps),
                        "plan": {**plan.progress(steps), "source": "hook" if hook else "transcript" if steps else ""},
                        "model": m.get("model") or sr.get("model") or "",
                        "effort": m.get("effort") or sr.get("effort") or "",
                        "context": m.get("context") or ctx.get("last"), "budget": ctx.get("budget"),
                        "output_tokens": tokens.get("output"), "cost_usd": cost_of(sr), "last_write": _iso(mtime),
                        "age_s": int(age)})
        return sorted(out, key=lambda r: (STATES.index(r["state"]), r["age_s"]))


# --- the graph's panels ---

def _priority(node: dict) -> str:
    props = node.get("props") or {}
    p = resume._priority(node)
    return p or (f"{props['priority_proposed']}?" if props.get("priority_proposed") else "")


def _is_open(st: resume.Store, nid: str) -> bool:
    n = st.nodes.get(nid) or {}
    if n.get("type") == "Milestone":
        return n.get("status") not in ("reached", "dropped")
    return n.get("type") == "WorkItem" and n.get("status") in resume.WORK_OPEN


def downstream(st: resume.Store) -> dict[str, set[str]]:
    """node -> the nodes that wait on it: its dependents (depends_on, gated_by) and its milestones (part_of)."""
    down: dict[str, set[str]] = {}
    for e in st.edges:
        if e.get("type") in ("depends_on", "gated_by"):
            down.setdefault(str(e["to"]), set()).add(str(e["from"]))
        elif e.get("type") == "part_of":
            down.setdefault(str(e["from"]), set()).add(str(e["to"]))
    return down


def unblocks(st: resume.Store, nid: str, down: dict[str, set[str]]) -> int:
    """How many open items and pending milestones wait on ``nid``, directly or through others (as brain queue
    counts an entry's)."""
    seen: set[str] = set()
    stack = [x for x in down.get(nid, ()) if x != nid]
    while stack:
        x = stack.pop()
        if x in seen or x == nid or not _is_open(st, x):
            continue
        seen.add(x)
        stack += down.get(x, ())
    return len(seen)


def _days(since: str, today: datetime) -> int | None:
    try:
        return (today.date() - datetime.fromisoformat(since).date()).days
    except ValueError:
        return None


def frontier_rows(st: resume.Store, today: datetime | None = None) -> list[dict]:
    """The startable items by priority, each with its milestone (its part_of target, else its milestone_proposed
    marked ``?``), what it unblocks and the age of its idea (the first date of its ``idea`` prop)."""
    today = today or datetime.now(timezone.utc)
    down = downstream(st)
    part_of = {}
    for e in sorted(st.edges, key=lambda e: str(e.get("to"))):
        if e.get("type") == "part_of" and (st.nodes.get(e["to"]) or {}).get("type") == "Milestone":
            part_of.setdefault(e["from"], e["to"])
    rows = []
    for n in status.frontier(st):
        props = n.get("props") or {}
        since = (_DATE_RE.findall(str(props.get("idea") or "")) or [""])[0]
        proposed = props.get("milestone_proposed")
        rows.append({"id": n["id"], "priority": _priority(n), "title": " ".join(str(n.get("title") or "").split()),
                     "milestone": part_of.get(n["id"]) or (f"{proposed}?" if proposed else ""),
                     "unblocks": unblocks(st, n["id"], down), "since": since,
                     "age_days": _days(since, today) if since else None})
    return sorted(rows, key=lambda r: (*_rank(r["priority"]), r["id"]))


def _rank(priority: str) -> tuple[int, bool]:
    """P0 first, a set priority before the same one proposed, none last."""
    return {p: i for i, p in enumerate(PRIORITIES)}.get(priority.rstrip("?"), 9), priority.endswith("?")


def perf_summary(names: set[str] | None, now: datetime) -> dict:
    """The execution-time ledger's last days (brain.perf): runs, failures, the slowest steps, the regressions."""
    since = now - timedelta(days=PERF_DAYS)
    runs, skipped = perf.load(since=since)
    runs = [r for r in runs if names is None or r.project in names]
    rep = perf.report(runs, skipped, since, now, top=3)
    return {"days": PERF_DAYS, "runs": rep["runs"], "failed": sum(1 for r in runs if not r.ok),
            "slowest": rep["slowest"], "regressions": rep["regressions"]}


# --- the panels of a scope ---

def _files(d: Path, pattern: str = "*") -> list[Path]:
    try:
        return sorted(d.glob(pattern)) if d.is_dir() else []
    except OSError:
        return []


def signature(files: list[Path]) -> tuple:
    """Each file's size and modification time: what the watch compares between two ticks."""
    out = []
    for f in files:
        try:
            st = f.stat()
            out.append((str(f), st.st_size, st.st_mtime_ns))
        except OSError:
            out.append((str(f), None, None))
    return tuple(out)


class Cockpit:
    """The panels of a scope (projects, or every one with ``every``), kept between refreshes: a tick re-reads the
    panels whose files changed, a probe the slow ones. Safe to call from one worker thread at a time."""

    def __init__(self, projs: list[projects.Project], *, every: bool = False, root: Path | None = None,
                 hours: float = HOURS) -> None:
        self.projs, self.every, self.root, self.hours = list(projs), every, root, hours
        try:
            registry = list(projects.load(root).values())
        except (OSError, ValueError):
            registry = []
        # the project selector's choices: the registry, the command's own projects first (a worktree keeps its root)
        self.choices = {p.name: p for p in registry + self.projs}
        self.choices.update({p.name: p for p in self.projs})
        self.sessions = Sessions(queue.Placer(registry + self.projs), hours)
        self.scanned: dict | None = None  # queue.scan, from the last probe
        self.probes: dict[str, dict] = {}  # project -> what its last probe measured, and when
        self.panels: dict[str, dict] = {}
        self.stores: dict[str, resume.Store] = {}  # project -> its graph, as the last read of the file panels
        self.sigs: dict[str, tuple] = {}
        self.dirty: set[str] = set()  # panels to draw again at the next refresh (a new scope)
        self.read_at: str | None = None
        self.probed_at: str | None = None
        self.lock = threading.Lock()

    @property
    def found(self) -> list[projects.Project]:
        return [p for p in self.projs if p.root.is_dir()]

    @property
    def scope(self) -> str:
        return ALL if self.every else ",".join(p.name for p in self.projs)

    @property
    def multi(self) -> bool:
        """More than one project in scope: the tables show the project column."""
        return self.every or len(self.projs) > 1

    def select(self, scope: str) -> None:
        """Every registered project (``all``) or one of ``choices``: the file panels are read again at the next
        refresh, the probed ones come back from what each project's last probe measured. Call it from the thread
        that refreshes."""
        if scope == ALL:
            projs, every = list(self.choices.values()), True
        elif scope in self.choices:
            projs, every = [self.choices[scope]], False
        else:
            raise KeyError(scope)
        self.projs, self.every, self.sigs = projs, every, {}
        with self.lock:
            self.panels = {k: v for k, v in self.panels.items() if k == "sessions"}
        self._probed_panels()
        self.dirty = set(PANELS)

    def needs_probe(self) -> bool:
        """A project in scope that no probe measured yet."""
        return any(p.name not in self.probes for p in self.found)

    def watched(self) -> dict[str, list[Path]]:
        """The files of each group of file panels (the sessions panel is read at every tick)."""
        graph = [f for p in self.found for s in p.stores for sub in ("nodes", "edges") for f in _files(s / sub)]
        graph += [f for p in self.found for f in _files(p.root / "records" / "ddr", "*.yaml")]
        graph += [j for p in self.found for j in p.journals] + _files(paths.ledger_dir(), "queue-*.jsonl")
        return {"graph": graph}

    def changed(self) -> set[str]:
        """The groups whose files changed since the last call (every group the first time)."""
        new = {g: signature(fs) for g, fs in self.watched().items()}
        out = {g for g, s in new.items() if self.sigs.get(g) != s}
        self.sigs.update(new)
        return out

    def _set(self, **panels) -> None:
        with self.lock:
            self.panels.update(panels)

    def _queue(self) -> dict:
        rows = status.queue_rows(self.found or self.projs, self.every, self.root, with_graph=False,
                                 transcripts=self.scanned is not None, scanned=self.scanned)
        shown = rows if self.every else [r for r in rows if r["project"] != OUTSIDE]  # as brain queue shows them
        return {"days": queue.DAYS, "denials_read": self.scanned is not None,
                "outside": sum(len(r["entries"]) for r in rows if r not in shown),
                "projects": [{k: r.get(k) for k in ("project", "counts", "entries", "guard_refusals")} for r in shown]}

    def read_sessions(self, now: float | None = None) -> bool:
        """The sessions panel read again; True when what it shows changed (a state, a step, an age)."""
        only = None if self.every else {p.name for p in self.projs}
        new = {"hours": self.hours, "rows": self.sessions.rows(only, now)}
        with self.lock:
            old = self.panels.get("sessions")
            self.panels["sessions"] = new
        return old is None or table("sessions", old) != table("sessions", new)

    def read_graph(self) -> None:
        stores = {p.name: status._store(p) for p in self.found}
        self.stores.update(stores)  # the detail pane (brain.detail) reads them instead of the disk
        self._set(milestones={"projects": [{"project": n, **status.milestones(st)} for n, st in stores.items()]},
                  frontier={"projects": [{"project": n, "items": frontier_rows(st)} for n, st in stores.items()]},
                  queue=self._queue())

    def probe(self, now: datetime | None = None) -> None:
        """The slow panels: alerts, audit, health, digest, and the queue again with a new scan of the denied calls.
        The alerts come from what the probe measured (as brain status and brain alerts compute them) and the
        scheduler, read once."""
        now = now or datetime.now(timezone.utc)
        self.scanned = queue.scan(queue.DAYS)
        stack_reg, index = status._probes(self.root, False)
        found = self.found
        measured = {p.name: {"audit": status.audit_of(p, detail=AUDIT_TOP), **status.probed(p, stack_reg, index)}
                    for p in found}
        sched, last = alerts.read_scheduler(status._alert_configs(found)), alerts.state_load()
        at = transcript.iso(now)
        for p in found:
            m = measured[p.name]
            self.probes[p.name] = {
                "at": at, "alerts": {"project": p.name, **status.alerts_of(p, m, stack_reg, sched, last)},
                "audit": {"project": p.name, **m["audit"]},
                "health": {"project": p.name, "stacks": m["stacks"], "code_index": m["code_index"]},
                "digest": digest_of(p)}
        self._probed_panels(now)
        self._set(queue=self._queue())

    def _probed_panels(self, now: datetime | None = None) -> None:
        """The probed panels of the scope, from what each project's last probe measured (none: not probed yet)."""
        got = [self.probes[p.name] for p in self.found if p.name in self.probes]
        with self.lock:
            for name in PROBE_PANELS:
                self.panels.pop(name, None)
        if got:
            now = now or datetime.now(timezone.utc)
            self._set(alerts={"projects": [g["alerts"] for g in got]},
                      audit={"projects": [g["audit"] for g in got]},
                      health={"projects": [g["health"] for g in got],
                              "exec": perf_summary(None if self.every else {p.name for p in self.projs}, now)},
                      digest={"projects": [g["digest"] for g in got]})
        self.probed_at = min(g["at"] for g in got) if got and not self.needs_probe() else None

    def refresh(self, probe: bool = False) -> set[str]:
        """One tick: the sessions (a transcript only when it changed), the file panels whose files changed (all of
        them the first time), then the probes when asked; the panels whose content changed."""
        groups = self.changed()
        if "graph" in groups:
            self.read_graph()
        updated = {p for g in groups for p in FILE_PANELS[g]} | self.dirty
        self.dirty = set()
        if self.read_sessions():
            updated.add("sessions")
        if probe:
            self.probe()
            updated |= {*PROBE_PANELS, "queue"}
        if updated:
            self.read_at = transcript.iso(datetime.now(timezone.utc))
        return updated

    def snapshot(self) -> dict:
        with self.lock:
            panels = dict(self.panels)
        return {"cockpit": 1, "scope": self.scope,
                "projects": [{"name": p.name, "root": str(p.root), "found": p.root.is_dir()} for p in self.projs],
                "read_at": self.read_at, "probed_at": self.probed_at, "panels": panels}


# --- the view: filters, sort and search over the table panels ---

SORTS = {"sessions": ("state", "age", "project", "context", "cost"),
         "queue": ("band", "unblocks", "age", "kind", "project"),
         "frontier": ("priority", "unblocks", "milestone", "age", "project")}
FILTERS = {"sessions": {"state": ("open", ALL, *STATES)},  # open: not ended
           "queue": {"kind": (ALL, *queue.KINDS), "band": (ALL, *queue.BANDS)},
           "frontier": {"priority": (ALL, "P0-P1", "P0-P2", "none"), "milestone": (ALL, "none")}}
OPEN_VALUES = {("frontier", "milestone")}  # any milestone id too: the panel's own (choices)
SORT_COLUMNS = {"sessions": {"State": "state", "Last": "age", "Project": "project", "Context": "context"},
                "queue": {"Band": "band", "Unblocks": "unblocks", "Age": "age", "Kind": "kind", "Project": "project"},
                "frontier": {"P": "priority", "Unblocks": "unblocks", "Milestone": "milestone", "Age": "age",
                             "Project": "project"}}


def _age_first(days) -> int:
    return -(days if days is not None else -1)  # the oldest first, an unknown age last


SORT_KEYS = {
    "sessions": {"state": lambda r: (STATES.index(r["state"]), r["age_s"]), "age": lambda r: r["age_s"],
                 "project": lambda r: (r["project"], STATES.index(r["state"]), r["age_s"]),
                 "context": lambda r: -(r.get("context") or 0),
                 "cost": lambda r: (r.get("cost_usd") is None, -(r.get("cost_usd") or 0), r["age_s"])},
    "queue": {"band": lambda e: (queue.BANDS.index(e.get("band") or "later"), e.get("order") is None,
                                 e.get("order") or 0, -e.get("score", 0), -e.get("unblocks", 0)),
              "unblocks": lambda e: (-e.get("unblocks", 0), not e.get("blocking"), e.get("since") or "9999"),
              "age": lambda e: (_age_first(e.get("age_days")), -e.get("unblocks", 0)),
              "kind": lambda e: (e.get("kind") or "", e.get("category") or "", -e.get("unblocks", 0)),
              "project": lambda e: (e["project"], -e.get("unblocks", 0))},
    "frontier": {"priority": lambda i: _rank(i["priority"]),
                 "unblocks": lambda i: (-i.get("unblocks", 0), *_rank(i["priority"])),
                 "milestone": lambda i: (i.get("milestone", "").rstrip("?") or "~", i.get("milestone", "").endswith("?"),
                                         *_rank(i["priority"])),
                 "age": lambda i: (_age_first(i.get("age_days")), *_rank(i["priority"])),
                 "project": lambda i: (i["project"], *_rank(i["priority"]))},
}


def view_of(name: str, saved: dict | None = None) -> dict:
    """A panel's view: ``saved``'s sort, order and filters over the defaults (the first of each); a value the panel
    does not know is left out."""
    out = {"sort": SORTS[name][0], "reverse": False, **{f: v[0] for f, v in FILTERS[name].items()}}
    for k, v in (saved or {}).items():
        if k == "sort" and v in SORTS[name]:
            out[k] = v
        elif k == "reverse":
            out[k] = bool(v)
        elif k in FILTERS[name] and isinstance(v, str) and (v in FILTERS[name][k] or (name, k) in OPEN_VALUES):
            out[k] = v
    return out


def entries(name: str, panel: dict | None) -> list[dict]:
    """A table panel's records, each with its project, in the panel's order."""
    panel = panel or {}
    if name == "sessions":
        return list(panel.get("rows") or [])
    key = {"queue": "entries", "frontier": "items", "milestones": "pending", "alerts": "alerts"}[name]
    return [{**r, "project": g["project"]} for g in panel.get("projects") or [] for r in g.get(key) or []]


def _keep(name: str, r: dict, v: dict) -> bool:
    if name == "sessions":
        return v["state"] == ALL or (r["state"] != "ended" if v["state"] == "open" else r["state"] == v["state"])
    if name == "queue":
        return v["kind"] in (ALL, r.get("kind")) and v["band"] in (ALL, r.get("band") or "later")
    p, m = r.get("priority", "").rstrip("?"), r.get("milestone", "").rstrip("?")
    by_p = (v["priority"] == ALL or (v["priority"] == "none" and not p)
            or (v["priority"].startswith("P0-") and p in PRIORITIES[:int(v["priority"][-1]) + 1]))
    return by_p and (v["milestone"] == ALL or (v["milestone"] == "none" and not m) or m == v["milestone"])


def haystack(name: str, r: dict) -> str:
    """What the search looks in: the row's ids, project, title and the words shown with them."""
    keys = {"sessions": ("session_id", "project", "state", "step", "title", "branch", "model"),
            "queue": ("id", "kind", "category", "band", "project", "title", "recommended", "detail"),
            "frontier": ("id", "priority", "project", "milestone", "title"),
            "milestones": ("id", "project", "title"), "alerts": ("level", "project", "key", "message")}[name]
    return " ".join(str(r.get(k) or "") for k in keys).lower()


def shown(name: str, panel: dict | None, view: dict | None = None, search: str = "") -> list[dict]:
    """The records a view keeps, in its order: its filters, then the search (every word of it, case ignored), then
    its sort (ties keep the panel's order). ``view`` None: no filter, the panel's order."""
    rows = entries(name, panel)
    v = view_of(name, view) if view is not None and name in SORTS else None
    if v:
        rows = [r for r in rows if _keep(name, r, v)]
    words = search.lower().split()
    if words:
        rows = [r for r in rows if all(w in haystack(name, r) for w in words)]
    if v:
        rows = sorted(rows, key=SORT_KEYS[name][v["sort"]], reverse=v["reverse"])
    return rows


def choices(name: str, field: str, panel: dict | None) -> tuple[str, ...]:
    """A filter's values: its fixed ones, then (the frontier's milestone) the panel's own, sorted."""
    fixed = FILTERS[name][field]
    if (name, field) not in OPEN_VALUES:
        return fixed
    own = {str(r.get(field) or "").rstrip("?") for r in entries(name, panel)} - {""}
    return (*fixed, *sorted(own))


def note(name: str, panel: dict | None, view: dict | None, search: str = "", sort: bool = False) -> str:
    """The view in a few words: what is shown out of what, the filters set (a default one only when it hides a
    row), the search and (``sort``, or when it is not the default) the sort."""
    total, n = len(entries(name, panel)), len(shown(name, panel, view, search))
    v = view_of(name, view) if view is not None and name in SORTS else None
    parts = [f"{n} of {total} shown"] if n != total else []
    parts += [f"{f} {v[f]}" for f, vals in FILTERS[name].items()
              if v[f] != vals[0] or (v[f] != ALL and n != total)] if v else []
    parts += [f"search '{search.strip()}'"] if search.strip() else []
    if v and (sort or v["sort"] != SORTS[name][0] or v["reverse"]):
        parts.append(f"sort {v['sort']}" + (" reversed" if v["reverse"] else ""))
    return "; ".join(parts)


def _noted(line: str, name: str, panel: dict | None, view: dict | None, search: str) -> str:
    text = note(name, panel, view, search)
    return f"{line} [{text}]" if text else line


def parse_view(sorts: list[str] | None = None, filters: list[str] | None = None) -> dict[str, dict]:
    """``--sort PANEL:KEY`` (``PANEL:-KEY`` reversed) and ``--filter PANEL:FIELD=VALUE`` as each panel's view;
    ValueError on a panel, key, field or value it does not know."""
    out: dict[str, dict] = {}

    def panel_of(text: str, what: str) -> tuple[str, str]:
        name, _, rest = text.partition(":")
        if name not in SORTS or not rest:
            raise ValueError(f"{text!r}: {what} as PANEL:..., PANEL one of {', '.join(SORTS)}")
        return name, rest

    for s in sorts or []:
        name, key = panel_of(s, "a sort")
        rev = key.startswith("-")
        if key.lstrip("-") not in SORTS[name]:
            raise ValueError(f"{s!r}: {name} sorts by {', '.join(SORTS[name])}")
        out.setdefault(name, {}).update(sort=key.lstrip("-"), reverse=rev)
    for f in filters or []:
        name, rest = panel_of(f, "a filter")
        field, _, value = rest.partition("=")
        if field not in FILTERS[name] or not value:
            raise ValueError(f"{f!r}: {name} filters on {', '.join(f'{k}=VALUE' for k in FILTERS[name])}")
        if value not in FILTERS[name][field] and (name, field) not in OPEN_VALUES:
            raise ValueError(f"{f!r}: {name} {field} is one of {', '.join(FILTERS[name][field])}")
        out.setdefault(name, {})[field] = value
    return out


def when(iso: str | None, tz: str | None = "local", fmt: str = "%H:%M:%S") -> str:
    """An ISO time (``...Z``) in ``tz``: ``local`` (this machine's timezone) or ``utc``; '-' without one, the text
    itself when it is not a time."""
    if not iso:
        return "-"
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return (t.astimezone() if tz == "local" else t.astimezone(timezone.utc)).strftime(fmt)


# --- what each panel shows: the TUI's i ---

HELP = {
    "sessions": {"what": "The sessions whose transcript was written in the last --hours (24): state, session, project, "
                         "step n/m of its plan, model, effort, context used and its budget, output tokens, last write, "
                         "title or branch. asking: a question to {owner} or a blocked wrap-up; running; stale: nothing "
                         "written for 15 min; idle: its turn ended; ended: the SessionEnd hook recorded its end.",
                 "from": "the transcripts' tails, the SR snapshots of the Stop hook (~/.brain/sessions/<id>.json), "
                         "the plans (the PostToolUse hook's <id>.plan.json, else the transcript's plan calls), the "
                         "ledger's SessionEnd events",
                 "read": "every --refresh (2 s), a transcript only when it changed",
                 "detail": "brain status; the session's own transcript"},
    "queue": {"what": "What waits on {owner}: decisions (DDRs, open questions on items), actions (keys, money, accounts, "
                      "scheduled tasks...) and permissions (denied calls), in three bands (now, this week, when you "
                      "can) ranked by what each holds up: the priority and count of the open items and milestones it "
                      "unblocks, the critical path's slip per day of waiting, the nearest milestone, a deadline, the "
                      "minutes it takes, its age ({owner}'s own order first: brain queue order); brain queue --explain "
                      "shows each term. The title is {owner}'s display name (config.json identity.display_name), or "
                      "a free one in tui.json settings.titles.queue.",
              "from": "brain.queue.collect, as brain queue: records/ddr, the items' open props, the transcripts' "
                      "denied calls, the queue's done stamps",
              "read": "when the graph, a DDR, a journal or a done stamp changes; the denied calls at each probe",
              "detail": "brain queue; brain decision pending; brain decision answer <id> <option>"},
    "alerts": {"what": "Each project's open alerts by level: missed or failed scheduled tasks, stacks down, a stale "
                       "code index, audit debt above its written view, alert events and alert files.",
               "from": "brain.status.alerts_of, as brain status and brain alerts (the scheduler, the exec ledger, the "
                       "stacks, the code index, the audit, the alert events and files)",
               "read": "at each probe (--probe, 5 min, and r)",
               "detail": "brain alerts --project <p>"},
    "milestones": {"what": "Each pending milestone: its items done out of its live items, and how many are reached.",
                   "from": "the graph: the Milestone nodes and the part_of edges (brain.status.milestones)",
                   "read": "when a graph file changes",
                   "detail": "research_graph milestone <id>; brain milestone suggest"},
    "frontier": {"what": "The startable todo items (every depends_on and gated_by satisfied) by priority, a proposed "
                         "priority marked ?, with the milestone each is part of (or proposed for, ?), the open items "
                         "and milestones it unblocks, and the age of its idea.",
                 "from": "the graph (brain.status.frontier, brain.cockpit.frontier_rows)",
                 "read": "when a graph file changes",
                 "detail": "research_graph work-frontier; brain item set <id> priority=P1"},
    "audit": {"what": "The audit debt: the findings by severity and repo, the first P0 and P1 ones.",
              "from": "brain.status.audit_of, as brain audit (every repo of the project)",
              "read": "at each probe",
              "detail": "brain audit --project <p>"},
    "health": {"what": "Each stack's and each code index repo's state, and the exec-time ledger's last 7 days (runs, "
                       "failures, regressions).",
               "from": "brain.status.probed, as brain health and brain index; brain.perf",
               "read": "at each probe",
               "detail": "brain health; brain index; brain perf"},
    "digest": {"what": "The journals' last day and the records, then the latest written digest, else last week's built "
                       "offline.",
               "from": "brain.status.records_of, brain.digest",
               "read": "at each probe",
               "detail": "brain digest; brain resume"},
}


def help_lines(name: str) -> list[str]:
    """A panel's help: what it shows, where it comes from, how often it is read, the commands for the detail, and
    its keys. ``{owner}`` in a text is config.json's owner."""
    h = {k: v.replace("{owner}", config.name_of()) for k, v in HELP[name].items()}
    keys = ("s next sort, o reverse, f filters and sort, a column title sorts; " if name in SORTS else "")
    return [h["what"], "", f"From: {h['from']}.", f"Read: {h['read']}.", f"Detail: {h['detail']}.", "",
            f"Keys: {keys}/ search, m full view (Escape back), {PANELS.index(name) + 1} to come back here."]


# --- the screen's remembered state: <BRAIN_HOME>/tui.json ---

def state_path() -> Path:
    return paths.brain_home() / STATE_FILE


def load_state(path: Path | None = None) -> dict:
    """The scope, the panels' views and the settings (``theme``, ``tz``) the interactive cockpit last showed; {}
    without them (the file missing, unreadable or not this shape)."""
    try:
        data = json.loads((path or state_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    if isinstance(data.get("scope"), str) and data["scope"]:
        out["scope"] = data["scope"]
    if isinstance(data.get("panels"), dict):
        out["panels"] = {n: view_of(n, v) for n, v in data["panels"].items() if n in SORTS and isinstance(v, dict)}
    if isinstance(data.get("settings"), dict):
        got = data["settings"]
        out["settings"] = {k: got[k] for k in ("theme", "tz", "lang") if isinstance(got.get(k), str) and got[k]
                           and (k != "tz" or got[k] in TZS) and (k != "lang" or got[k] in LANGS)}
        if isinstance(got.get("titles"), dict):
            titles = {k: v.strip() for k, v in got["titles"].items()
                      if k in PANELS and isinstance(v, str) and v.strip()}
            if titles:
                out["settings"]["titles"] = titles
    return out


# --- the panels' titles: the owner's display name, the language, a free title per panel (wi-brain-owner-label) ---

LANGS = ("en", "fr")
TITLES = {"sessions": "Sessions", "alerts": "Alerts", "milestones": "Milestones", "frontier": "Frontier",
          "audit": "Audit debt", "health": "Stacks and index", "digest": "Digest"}
QUEUE_TITLES = {"en": ("{name}'s queue", "My queue"), "fr": ("File de {name}", "Ma file")}  # (named, unnamed)
_VOWELS = "aeiouyàâäéèêëîïôöûùü"
_settings_cache: dict = {}


def settings() -> dict:
    """tui.json's settings (theme, tz, lang, titles), read again only when the file changed."""
    path = state_path()
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return {}
    if _settings_cache.get("key") != key:
        _settings_cache.update(key=key, value=load_state(path).get("settings") or {})
    return _settings_cache["value"]


def lang() -> str:
    """The cockpit's language: $BRAIN_LANG, else tui.json's settings.lang, else en."""
    got = os.environ.get("BRAIN_LANG") or settings().get("lang") or "en"
    return got if got in LANGS else "en"


def queue_title(name: str | None = None, language: str | None = None) -> str:
    """The queue's title (UX-16): « {name}'s queue » / « File de {name} » (« File d'{name} » before a vowel)
    from the owner's display name (config.name_of), « My queue » / « Ma file » when no one is named."""
    name = config.name_of() if name is None else name
    named, mine = QUEUE_TITLES[language if language in LANGS else lang()]
    if not name or name == config.NO_OWNER:
        return mine
    if named.startswith("File de ") and name[:1].lower() in _VOWELS:
        return f"File d'{name}"
    return named.format(name=name)


def title(name: str) -> str:
    """A panel's title: the person's free title (tui.json settings.titles.<panel>), else the queue's
    :func:`queue_title` or the panel's name."""
    return (settings().get("titles") or {}).get(name) or (queue_title() if name == "queue" else TITLES[name])


def save_state(state: dict, path: Path | None = None) -> bool:
    """Written whole (a temporary file, then replaced); False when it could not be (never raised)."""
    path = path or state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"cockpit": 1, **state}, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                       encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def digest_of(p: projects.Project) -> dict:
    latest = digest.latest(p.name)
    if latest is not None:
        text, name, written = latest.read_text(encoding="utf-8"), latest.stem, True
    else:
        text, name, written = digest.build(p, offline=True), "last-week", False
    return {"project": p.name, "records": status.records_of(p), "digest": name, "written": written, "text": text}


# --- text ---

def tokens(n) -> str:
    """605k, 1.2M, 950; '-' when unknown."""
    if not isinstance(n, (int, float)):
        return "-"
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else str(int(n))


def ago(seconds: float) -> str:
    return "now" if seconds < 60 else resume.age(seconds)


_cut = decisions._short  # one line, cut to n characters


def _line(indent: str, text: str, width: int) -> str:
    return indent + _cut(text, max(width - len(indent), 20))


def bar(done: int, total: int, width: int = 10) -> str:
    full = round(width * done / total) if total else 0
    return "#" * full + "." * (width - full)


def context_text(r: dict) -> str:
    return tokens(r.get("context")) + (f"/{tokens(r['budget'])}" if r.get("budget") else "")


def model_text(r: dict) -> str:
    return str(r.get("model") or "-").removeprefix("claude-")


def session_lines(panel: dict, width: int = WIDTH, view: dict | None = None, search: str = "") -> list[str]:
    rows = panel.get("rows") or []
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in STATES}
    lines = [_noted(f"{title('sessions')} ({len(rows)} in the last {panel.get('hours', HOURS):g} h"
                    + "".join(f", {n} {s}" for s, n in counts.items() if n) + ")", "sessions", panel, view, search)]
    rows = shown("sessions", panel, view, search)
    if rows:
        lines.append("  state    session  project    model    effort context   out      last  step | title")
    for r in rows:
        head = (f"  {r['state']:<8} {r['session_id'][:8]} {r['project'][:10]:<10} {model_text(r)[:8]:<8} "
                f"{str(r.get('effort') or '-')[:6]:<6} {context_text(r):<9} {tokens(r['output_tokens']):<5} "
                f"{ago(r['age_s']):>7}  ")
        lines.append(_line(head, f"{r['step'] or '(no plan)'} | {r['title'] or r['branch']}", width))
    return lines


def queue_lines(panel: dict, width: int = WIDTH, view: dict | None = None, search: str = "") -> list[str]:
    groups = panel.get("projects") or []
    total = {k: sum((g.get("counts") or {}).get(k, 0) for g in groups) for k in queue.KINDS}
    b = {k: sum(1 for e in entries("queue", panel) if e.get("band") == k) for k in queue.BANDS}
    lines = [_noted(f"{title('queue')} ({sum(total.values())}: "
                    + ", ".join(f"{n} {k}" for k, n in total.items())
                    + (" | " + ", ".join(f"{queue.BAND_NAMES[k]} {n}" for k, n in b.items()) if any(b.values())
                       else "") + ")"
                    + ("" if panel.get("denials_read") else "; denied calls read at the first probe")
                    + (f"; {panel['outside']} denial(s) outside every project (--all)" if panel.get("outside")
                       else ""), "queue", panel, view, search)]
    for e in shown("queue", panel, view, search):
        tag = e["kind"] + (f":{e['category']}" if e.get("category") else "")
        age = f"{e['age_days']} d" if e.get("age_days") is not None else "-"
        text = e["title"] + (f" -> {e['recommended']}" if e.get("recommended") else "")
        band = queue.BAND_NAMES.get(e.get("band"), "-")
        score = f"{e['score']:g}" if e.get("score") is not None else "-"
        head = f"  {band:<12} {score:>5} {e['unblocks']:>3} {tag:<16} {e['project'][:10]:<10} {age:>5}  "
        lines.append(_line(head, f"{e['id']}{' [blocking]' if e.get('blocking') else ''}: {text}", width))
    return lines


def alert_lines(panel: dict | None, width: int = WIDTH) -> list[str]:
    if not panel:
        return [f"{title('alerts')}: not probed yet"]
    groups = panel.get("projects") or []
    counts: dict[str, int] = {}
    for g in groups:
        for lvl, n in (g.get("counts") or {}).items():
            counts[lvl] = counts.get(lvl, 0) + n
    lines = [f"{title('alerts')} ({sum(counts.values())} open" + "".join(f", {n} {k}" for k, n in counts.items()) + ")"]
    for g in groups:
        if "error" in g:
            lines.append(_line("  ", f"{g['project']}: error: {g['error']}", width))
        for a in g.get("alerts") or []:
            lines.append(_line(f"  {a['level'].upper():<8} {g['project'][:10]:<10} ", f"{a['key']}: {a['message']}",
                               width))
    return lines


def milestone_lines(panel: dict, width: int = WIDTH) -> list[str]:
    groups = panel.get("projects") or []
    lines = [f"{title('milestones')} ({sum(g['reached'] for g in groups)} reached, "
             f"{sum(len(g['pending']) for g in groups)} pending)"]
    for g in groups:
        for m in g["pending"]:
            head = f"  {g['project'][:10]:<10} {m['done']:>3}/{m['items']:<3} {bar(m['done'], m['items'])}  "
            lines.append(_line(head, f"{m['id']}: {m['title']}", width))
    return lines


def short_milestone(mid: str, project: str) -> str:
    """ms-brain-cockpit -> cockpit (the project's prefix left out), a proposed one keeping its ``?``."""
    return mid.removeprefix("ms-").removeprefix(f"{project}-") if mid else "-"


def frontier_lines(panel: dict, width: int = WIDTH, top: int = 15, view: dict | None = None,
                   search: str = "") -> list[str]:
    everything = entries("frontier", panel)
    lines = [_noted(f"{title('frontier')} ({len(everything)} startable, "
                    f"{sum(1 for i in everything if i['priority'] in ('P0', 'P1'))} of them P0/P1)", "frontier", panel,
                    view, search)]
    rows = shown("frontier", panel, view, search)
    for i in rows[:top or None]:
        head = f"  {i['priority'] or '-':<4} {i['project'][:10]:<10} {i.get('unblocks', 0):>3}  "
        lines.append(_line(head, f"{i['id']}: {i['title']}", width))
    if top and len(rows) > top:
        lines.append(f"  ... {len(rows) - top} more (the TUI lists them all)")
    return lines


def _counts(c: dict) -> str:
    return ", ".join(f"{k} {c.get(k, 0)}" for k in (*audit.SEVERITIES, "info"))


def audit_lines(panel: dict | None, width: int = WIDTH) -> list[str]:
    if not panel:
        return [f"{title('audit')}: not probed yet"]
    lines = [title("audit")]
    for g in panel.get("projects") or []:
        if "counts" not in g:
            lines.append(f"  {g['project']}: error: {g.get('error')}")
            continue
        lines.append(f"  {g['project']}: {_counts(g['counts'])} ({g['repos']} repo(s))")
        lines += [f"    {r['repo']}: {_counts(r['counts'])}" for r in g.get("by_repo") or [] if len(g["by_repo"]) > 1]
        for f in g.get("top") or []:
            lines.append(_line("    ", f"{f['severity']} {f['repo']} {f['check']} {f['unit']}: {f['why']}", width))
    return lines


def _states(rows, what: str) -> str:
    if isinstance(rows, dict):
        return f"error: {rows.get('error')}"
    if not rows:
        return f"no {what} declared"
    bad = [r for r in rows if r.get("state") != "OK"]
    return f"{len(rows) - len(bad)} of {len(rows)} OK" + "".join(
        f"; {r.get('name') or r.get('repo')} {r['state']}" + (f" ({r['why']})" if r.get("why") else "") for r in bad)


def health_lines(panel: dict | None, width: int = WIDTH) -> list[str]:
    if not panel:
        return [f"{title('health')}: not probed yet"]
    lines = [title("health")]
    for g in panel.get("projects") or []:
        lines.append(_line("  ", f"{g['project']}: stacks {_states(g['stacks'], 'stack')}; code index "
                                 f"{_states(g['code_index'], 'repo')}", width))
    ex = panel.get("exec") or {}
    if ex:
        reg = "; ".join(f"{r['task']} +{r['change']:.0%}" for r in ex.get("regressions") or [])
        lines.append(_line("  ", f"exec ledger: {ex['runs']} run(s) in {ex['days']} d, {ex['failed']} failed, "
                                 f"{len(ex.get('regressions') or [])} regression(s)" + (f": {reg}" if reg else ""),
                           width))
    return lines


def digest_lines(panel: dict | None, width: int = WIDTH, lines_max: int = 12) -> list[str]:
    """The digest panel's text: its first ``lines_max`` lines per project (0: all of them)."""
    if not panel:
        return [f"{title('digest')}: not probed yet"]
    lines = []
    for g in panel.get("projects") or []:
        rec = g["records"]
        journal = "; ".join(f"{Path(j['path']).name} {j['last'] or 'no entry'}" for j in rec.get("journals") or [])
        r = rec.get("records") or {}
        lines.append(f"Digest {g['project']} ({g['digest']}{', written' if g['written'] else ', built offline'}); "
                     f"journal {journal or '-'}" + (f"; {r['ddr']} DDR, {r['sr']} SR, {r['ar']} AR" if r else ""))
        body = [x for x in g["text"].splitlines() if x.strip()]
        lines += [_line("  ", x, width) for x in body[:lines_max or None]]
        if lines_max and len(body) > lines_max:
            lines.append(f"  ... {len(body) - lines_max} more line(s) (brain digest)")
    return lines or ["Digest: no project found"]


# --- the TUI's tables: plain strings, one tuple per row ---

COLUMNS = {
    "sessions": ("State", "Session", "Project", "Step", "Model", "Effort", "Context", "Out", "Last", "Title"),
    "queue": ("Band", "Score", "Unblocks", "Kind", "Project", "Age", "What", "Id"),
    "alerts": ("Level", "Project", "Key", "Since", "Message"),
    "milestones": ("Project", "Done", "Progress", "Milestone", "Title"),
    "frontier": ("P", "Project", "Unblocks", "Milestone", "Age", "Id", "Title"),
}


def _days_text(days) -> str:
    return f"{days} d" if days is not None else "-"


def cells(name: str, r: dict, project: bool = True, tz: str | None = None) -> tuple[str, ...]:
    """One record of a table panel (an item of ``entries``) as its row, ``columns(name, project)``; its times in
    ``tz`` (None: as recorded, UTC)."""
    row = _cells(name, r, tz)
    if project:
        return row
    i = COLUMNS[name].index("Project")
    return row[:i] + row[i + 1:]


def _cells(name: str, r: dict, tz: str | None = None) -> tuple[str, ...]:
    if name == "sessions":
        return (r["state"], r["session_id"][:8], r["project"], r["step"] or "-", model_text(r),
                str(r.get("effort") or "-"), context_text(r), tokens(r["output_tokens"]), ago(r["age_s"]),
                r["title"] or r["branch"])
    if name == "queue":
        return (queue.BAND_NAMES.get(r.get("band"), "-") + (f" #{r['order']}" if r.get("order") is not None else ""),
                f"{r['score']:g}" if r.get("score") is not None else "-", str(r["unblocks"]),
                r["kind"] + (f":{r['category']}" if r.get("category") else ""), r["project"],
                _days_text(r.get("age_days")), r["title"] + (f" -> {r['recommended']}" if r.get("recommended") else ""),
                r["id"] + (" [blocking]" if r.get("blocking") else ""))
    if name == "alerts":
        since = (when(r.get("since"), tz, "%Y-%m-%d %H:%M") if tz else str(r.get("since") or "-")[:16].replace("T", " "))
        return (r["level"], r["project"], r["key"], since, r["message"])
    if name == "milestones":
        return (r["project"], f"{r['done']}/{r['items']}", bar(r["done"], r["items"]), r["id"], r["title"])
    if name == "frontier":
        return (r["priority"] or "-", r["project"], str(r.get("unblocks", 0)),
                short_milestone(r.get("milestone", ""), r["project"]), _days_text(r.get("age_days")), r["id"],
                r["title"])
    raise KeyError(name)


def row_key(name: str, r: dict) -> str:
    """A record's identity in its table, kept across refreshes and sorts (the cursor follows it)."""
    return r["session_id"] if name == "sessions" else f"{r['project']}/{r.get('id') or r.get('key')}"


def columns(name: str, project: bool = True) -> tuple[str, ...]:
    """A table's columns; without the project column when the scope holds one project."""
    return tuple(c for c in COLUMNS[name] if project or c != "Project")


def table(name: str, panel: dict | None, view: dict | None = None, search: str = "", project: bool = True,
          tz: str | None = None) -> list[tuple[str, ...]]:
    """The rows of a table panel (``columns(name, project)``): the records ``view`` and ``search`` keep, in its
    order (``view`` None: all of them, in the panel's order), their times in ``tz``."""
    if name not in COLUMNS:
        raise KeyError(name)
    return [cells(name, r, project, tz) for r in shown(name, panel, view, search)]


def heading(name: str, panel: dict | None) -> str:
    """A panel's one-line title with its counts (the first line of its text)."""
    lines = {"sessions": session_lines, "queue": queue_lines, "alerts": alert_lines, "milestones": milestone_lines,
             "frontier": frontier_lines, "audit": audit_lines, "health": health_lines}
    if name == "digest":
        return title("digest") if panel else f"{title('digest')}: not probed yet"
    return lines[name](panel if name in PROBE_PANELS else panel or {})[0]


def render(snap: dict, width: int = WIDTH, views: dict[str, dict] | None = None, search: str = "",
           tz: str | None = None) -> list[str]:
    """The text view: every panel, one after the other; ``views`` (each table panel's view, {} its defaults) and
    ``search`` narrow the sessions, the queue and the frontier (None: everything, in the panels' order); ``tz``
    shows the header's times in that timezone (None: as recorded, UTC)."""
    p = snap["panels"]

    def stamp(iso):
        return (f"{when(iso, tz, '%Y-%m-%d %H:%M:%S')} ({tz})" if iso else None) if tz else iso
    head = (f"brain cockpit: {snap['scope']}; files read {stamp(snap.get('read_at')) or '-'}, probes "
            f"{stamp(snap.get('probed_at')) or 'not run'}")
    out = [head]

    def v(name):
        return None if views is None else views.get(name, {})
    for lines in (session_lines(p.get("sessions") or {}, width, v("sessions"), search),
                  queue_lines(p.get("queue") or {}, width, v("queue"), search),
                  alert_lines(p.get("alerts"), width),
                  milestone_lines(p.get("milestones") or {}, width),
                  frontier_lines(p.get("frontier") or {}, width, view=v("frontier"), search=search),
                  audit_lines(p.get("audit"), width), health_lines(p.get("health"), width),
                  digest_lines(p.get("digest"), width)):
        out += ["", *lines]
    return out


def watch(cp: Cockpit, refresh_s: float = REFRESH_S, probe_s: float = PROBE_S, out=None, ticks: int = 0,
          views: dict[str, dict] | None = None, search: str = "", tz: str | None = None) -> int:
    """The text view redrawn in place when a panel changed (``brain tui --plain``, or no tui extra); Ctrl-C quits.
    ``views``, ``search`` and ``tz`` as ``render``'s. ``ticks``: stop after that many (tests)."""
    out = out or sys.stdout
    next_probe, n = 0.0, 0
    try:
        while True:
            probe = time.monotonic() >= next_probe
            if probe:
                next_probe = time.monotonic() + probe_s
            if cp.refresh(probe=probe):
                width = max(min(os.get_terminal_size(out.fileno()).columns, 160), 60) if out.isatty() else WIDTH
                out.write(("\x1b[2J\x1b[H" if out.isatty() else "")
                          + "\n".join(render(cp.snapshot(), width, views, search, tz)) + "\n")
                out.flush()
            n += 1
            if ticks and n >= ticks:
                return 0
            time.sleep(refresh_s)
    except KeyboardInterrupt:
        return 0
