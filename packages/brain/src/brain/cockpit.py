"""The cockpit's panels: ``brain tui [--project p | --all]`` (wi-brain-tui-cockpit; spec 2026-10-30 §3.6 and §3.14;
Q7: a file watch with a 2 s fallback re-read). This is the data layer, the standard library and brain only:
the Textual app (``brain.tui``, the ``tui`` extra) and the text view (``brain tui --once``, and ``--plain`` or no
extra: the same text redrawn in place) both draw it.

Eight panels, each read through the function its command already uses:

  sessions    the sessions whose transcript was written in the last ``--hours`` (24): its short name (else the app's
              id), role, parent and children live/started (brain.sessions: the app's files, the SessionStart events),
              project (the folder placed as
              brain queue places it), title, branch, step n/m of its plan (brain.plan: the hook's file, else the
              plan calls of the transcript), state, model, effort, context used, its budget and Ctx, the context as a
              share of the budget (a master's without a brief: brain.sessions.master_budget), output tokens and
              the cost at API prices (the SR snapshot the Stop hook writes, <BRAIN_HOME>/sessions/<id>.json, priced
              by brain.usage; the costliest first: ``--sort sessions:cost``), last write;
  queue       the owner's queue (brain.queue.collect, as brain queue calls it): decisions, actions, permissions, in
              three bands (now, this week, when you can), ranked by what each holds up (its score; brain queue
              --explain; ``--sort queue:score``: the score alone, across the bands), with the recommended option and
              how to answer; titled with the owner's display name;
  alerts      each project's open alerts by level (brain.status.alerts_of, as brain status and brain alerts: the
              scheduler, the exec ledger, the stacks, the code index, the audit, the alert events and files);
  milestones  each pending milestone's items done out of its live items, and how many are reached (brain.status);
  frontier    the startable todo items by priority, a proposed priority marked ``?`` (brain.status.frontier), with
              the milestone each is part of (or proposed for, marked ``?``), the open items and pending milestones
              downstream of it, and the age of its idea (the date its ``idea`` prop names);
  audit       the findings by severity and repo, the first P0 and P1 ones (brain.status.audit_of, as brain audit);
  health      each stack's and code index repo's state (brain.status, as brain health and brain index), this
              machine's dependency probes (brain.depprobes, as brain probes: run at each probe) and the
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

The states (wi-brain-tui-states, spec 2026-11-02 cockpit-ux §4.10): an empty table says why (``why_empty``: a filter
or the search hides N rows, with the key that changes it; a project not on this machine; nothing in the scope, the
owner named); a panel not probed yet says what it waits for (``probe_wait``: the probe's countdown, then its progress
per project); a read that fails keeps its panels' last content, its error and the time of the data shown in the
snapshot (``errors``, ``panel_at``), and is read again at the next tick (a probed panel: at the next probe); a stack
or a code index repo that is not OK names its last OK measure this cockpit saw; a project the registry names but this machine lacks is greyed in the
project selector (``scope_choices``).

The tabs (wi-brain-tui-layout, spec 2026-11-03 cockpit-ux-round2 §4.0, UX-18): ``TABS`` holds one tab per question the
owner asks, each with its key (0 to 9, a comma), its label, its question, its count (``tab_count``, in digits and signs)
and its views, each a list of panels (``tab_panels``). A tab without a view is not built yet: it arrives with its item,
its key waiting for it (``built_tabs``, ``not_built``). Under 120 columns or 30 rows (``narrow``) the bar is reduced to
its numbers, the active tab named (``tab_labels``), and the grid is not offered (``tab_views``); the text view and
``--tab`` print one tab's panels (``render``). The overview's default view is one card per tab (``cards``, UX-19): what
counts in that tab in a few lines, and the filters it opens with; the text view prints them with ``--tab overview``.
From 140 columns, on a tab that is one list, a row's detail sits beside it (``detail_beside``, UX-20, brain.tui_side).
Each table's columns can be chosen (``columns``, ``cells``: shown or hidden, their order, the longest a title may be;
``EXTRA_COLUMNS``, hidden by default) and are kept in ``tui.json``; ``palette`` is the command palette's entries, in data.

A plugged project's panels and tabs (wi-brain-command-plugins-cockpit, brain.plugin_panels) join these tables at the
start (``plug``): each panel ``<project>-<panel>`` gets its columns, sorts, filters, help and title from its plugin's
``COCKPIT`` declaration, and each of its tabs is placed after Resources, with no number; its rows are read when it is
first shown and at each probe (``PLUGGED``, ``refresh``).

Read-only: nothing here writes a record or a ledger, and nothing calls a model. The one file written is the screen's
own state, ``<BRAIN_HOME>/tui.json`` (the scope, each panel's view, the last tab and each tab's view, and the settings:
theme, timezone, each table's columns; ``save_state``), by the interactive views. Its settings also hold ``lang`` (en,
fr: the queue's title, « File d'Ada »; $BRAIN_LANG wins), ``titles`` (a free title per panel, ``{"queue": "Ma file"}``),
read by every view (``title``), and ``refresh`` and ``probe`` (seconds; ``--refresh`` and ``--probe`` win for one
launch): the Settings tab edits them (the comma, brain.settings; wi-brain-tui-settings), and they may be set by hand.
tui.json is a truth-local file (brain.stateio): ``v`` 1, a backup beside it and an atomic write; the keys this engine
does not know (at the top level, in panels, tabs, columns, settings and titles: a newer brain's) are kept through a
save; one a newer brain wrote is read but never written (« brain update »), and an unreadable one is set aside by the
next save.
"""

from __future__ import annotations

import json
import math
import os
import re
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import (__version__, alerts, audit, config, decisions, defaults, digest, paths, perf, plan, plugin_panels,
               projects, queue, quiet, ranking, resume, review, sessions, stateio, status, transcript, usage)

PANELS = ("sessions", "queue", "alerts", "milestones", "frontier", "audit", "health", "digest")
FRAMES = {"exec": "health"}  # a frame drawn from another panel's data, not a read of its own: the health tab's fourth
FILE_PANELS = {"graph": ("queue", "milestones", "frontier")}
PROBE_PANELS = ("alerts", "audit", "health", "digest")
HOURS = 24.0
STALE_S = 15 * 60
END_SLACK_S = 120  # a transcript written later than this after its session's end: resumed, not ended
TAIL_BYTES = 256 * 1024
REFRESH_S = 2.0  # Q7: the fallback re-read every 2 s
INTERVAL_MIN = 0.25  # the shortest refresh or probe interval (brain tui --refresh, --probe; the Settings tab)
INTERVAL_MAX = 86400.0  # and the longest a saved one may be: a day
PROBE_S = 300.0
AUDIT_TOP = 12
PERF_DAYS = 7
PRIORITIES = ("P0", "P1", "P2", "P3")
STATES = ("asking", "running", "stale", "idle", "ended")
MASTER_STEPS = (70, 80, 90)  # a master's context steps (ST-3; brain.budget's master watch): its row coloured
ASK_TOOLS = ("AskUserQuestion",)
WRAP_UP = "mcp__ccd_turn__wrap_up"
OUTSIDE = queue.OUTSIDE
WIDTH = 118
ALL = "all"  # the scope of every registered project
TZS = ("local", "utc")  # the cockpit's timezone: this machine's (the default), or UTC
STATE_FILE = "tui.json"
STATE_V = 1               # tui.json's v (brain.stateio)
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
        self.master_budget: int | None = None  # read once (config.json usage.master_budget, else the model's window)

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
        tree = sessions.Tree(sessions.app_index(), sessions.ledger_events(now)[0])  # the app's files: once per change
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
                        "context": m.get("context") or ctx.get("last"),
                        "budget": ctx.get("budget") or sessions.watch_state(sid).get("budget"),
                        "output_tokens": tokens.get("output"), "cost_usd": cost_of(sr), "last_write": _iso(mtime),
                        "age_s": int(age), **self._family(tree, sid)})
        states = {r["session_id"]: r["state"] for r in out}
        for r in out:  # a child is live while the app has not archived it (one the app does not know: until it ended)
            kids = [tree.nodes[k] for k in tree.children.get(r["key"], [])] if r["key"] else []
            r["kids_live"] = sum(1 for k in kids if self._kid_live(k, states))
            r["ctx_pct"], r["ctx_step"] = self._ctx(r)
        return sorted(out, key=lambda r: (STATES.index(r["state"]), r["age_s"]))

    @staticmethod
    def _kid_live(node: dict, states: dict[str, str]) -> bool:
        """brain.sessions.alive's reading: the app resumes its own sessions on a message, so a recorded end kills
        only a child the app does not know (review of #34, finding 24)."""
        if node.get("archived"):
            return False
        return node.get("source") == "app" or states.get(node.get("session")) != "ended"

    def _family(self, tree: "sessions.Tree", sid: str) -> dict:
        """The session's place in the tree (wi-brain-session-tree): app id, short name, role, parent, children."""
        key = tree.key_of(sid)
        if not key:
            return {"host_id": "", "name": "", "role": "solo", "parent_name": "", "kids": 0, "key": ""}
        node = tree.nodes[key]
        return {"host_id": node.get("host_id") or "", "name": node.get("name") or "", "role": tree.role(key),
                "parent_name": tree.parent_name(key) if node.get("parent") else "",
                "kids": len(tree.children.get(key, [])), "key": key}

    def _ctx(self, r: dict) -> tuple[float | None, int]:
        """(context as a % of the budget, the master's step reached: 0, 70, 80 or 90): the brief's budget, else a
        master's (usage.master_budget, else the model's window)."""
        budget = r.get("budget")
        if not budget and r.get("role") in ("master", "relay"):
            if self.master_budget is None:
                self.master_budget = sessions.master_budget()
            budget = self.master_budget
        if not budget or not r.get("context"):
            return None, 0
        pct = 100.0 * r["context"] / budget
        step = max((s for s in MASTER_STEPS if pct >= s), default=0) if r.get("role") in ("master", "relay") else 0
        return round(pct, 1), step


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
    rows, ranker = [], ranking.Ranker(st.nodes, st.edges)
    for n in status.frontier(st):
        props = n.get("props") or {}
        since = (_DATE_RE.findall(str(props.get("idea") or "")) or [""])[0]
        proposed = props.get("milestone_proposed")
        sc = ranker.score(n["id"])
        rows.append({"id": n["id"], "priority": _priority(n), "title": " ".join(str(n.get("title") or "").split()),
                     "milestone": part_of.get(n["id"]) or (f"{proposed}?" if proposed else ""),
                     "unblocks": unblocks(st, n["id"], down), "since": since,
                     "age_days": _days(since, today) if since else None, "size": sc.size, "value": sc.level,
                     "score": sc.score, "quick_win": sc.quick_win, "explain": sc.explain(),
                     "order": ranking.order_of(n)})
    return sorted(rows, key=lambda r: (*_rank(r["priority"]), _order(r), -r["score"], r["id"]))


def _order(row: dict) -> float:
    """The owner's explicit order of a frontier row (props.order, lower first), none last."""
    return math.inf if row.get("order") is None else row["order"]


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


def review_summary() -> dict:
    """The review error score (brain.review.score): the totals, the trend per wave and the lightening rule's verdict;
    {} when it cannot be read."""
    try:
        sc = review.score(labels=review.labels_now())   # a stamp counted in its wave's release now
    except Exception:  # noqa: BLE001 - a stamp no engine wrote never takes the health probe down
        return {}
    return {"total": sc["total"], "waves": sc["waves"][-3:], "lighten": sc["lighten"]}


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
        self.registry = bool(registry)  # False: no projects.yaml, the selector holds this folder's project only
        self.sessions = Sessions(queue.Placer(registry + self.projs), hours)
        self.scanned: dict | None = None  # queue.scan, from the last probe
        self.probes: dict[str, dict] = {}  # project -> what its last probe measured, and when
        self.panels: dict[str, dict] = {}
        self.stores: dict[str, resume.Store] = {}  # project -> its graph, as the last read of the file panels
        self.sigs: dict[str, tuple] = {}
        self.dirty: set[str] = set()  # panels to draw again at the next refresh (a new scope)
        self.read_at: str | None = None
        self.probed_at: str | None = None
        self.errors: dict[str, dict] = {}  # panel -> {at, error}: its last read failed, its last content kept
        self.panel_at: dict[str, str] = {}  # panel -> when its content was last read
        self.progress: dict | None = None  # the probe running: {what, n, total}
        self.last_ok: dict[tuple, str] = {}  # (project, stacks|code_index, name) -> its last OK measure
        self.dep_probes: dict | None = None  # this machine's dependency probes, from the last probe (brain.depprobes)
        self.plugged_tried: set[str] = set()  # the plugins' panels read once since the last scope or probe
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
        # the errors and data times were the old scope's
        self.errors = {k: v for k, v in self.errors.items() if k == "sessions"}
        self.panel_at = {k: v for k, v in self.panel_at.items() if k == "sessions"}
        self._probed_panels()
        self.dirty = set(PANELS)
        self.plugged_tried = set()  # the plugins' panels of the new scope: read at the next tick

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
        found = self.found or self.projs   # the decisions taken by default, to review (brain decision defaulted)
        late = defaults.total_line([p.root for p in found], defaults._iso(datetime.now(timezone.utc)))
        return {"days": queue.DAYS, "denials_read": self.scanned is not None, "defaulted": late,
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
        at = transcript.iso(now)
        found = self.found
        self.progress = {"what": "the denied calls", "n": 0, "total": len(found)}
        self.scanned = queue.scan(queue.DAYS)
        self.progress = {"what": "the dependency probes", "n": 0, "total": 1}
        from . import depprobes
        self.dep_probes = depprobes.run()   # first: the brain's alerts below read this run
        stack_reg, index = status._probes(self.root, False)
        measured = {}
        for i, p in enumerate(found, 1):
            self.progress = {"what": p.name, "n": i, "total": len(found)}
            measured[p.name] = m = {"audit": status.audit_of(p, detail=AUDIT_TOP), **status.probed(p, stack_reg, index)}
            self._last_ok(p.name, m, at)
        self.progress = {"what": "the alerts and digests", "n": 0, "total": len(found)}
        sched, last = alerts.read_scheduler(status._alert_configs(found)), alerts.state_load()
        for p in found:
            m = measured[p.name]
            self.probes[p.name] = {
                "at": at, "alerts": {"project": p.name, **status.alerts_of(p, m, stack_reg, sched, last)},
                "audit": {"project": p.name, **m["audit"]},
                "health": {"project": p.name, "stacks": m["stacks"], "code_index": m["code_index"]},
                "digest": digest_of(p)}
        self._probed_panels(now)
        self._set(queue=self._queue())

    def _last_ok(self, project: str, measured: dict, at: str) -> None:
        """Each stack and code index repo OK now is remembered at ``at``; one that is not carries ``last_ok``, its
        last OK measure this cockpit saw (none: never seen OK since it started)."""
        for kind in ("stacks", "code_index"):
            rows = measured.get(kind)
            for r in rows if isinstance(rows, list) else []:
                key = (project, kind, r.get("name") or r.get("repo"))
                if r.get("state") == "OK":
                    self.last_ok[key] = at
                elif key in self.last_ok:
                    r["last_ok"] = self.last_ok[key]

    def _probed_panels(self, now: datetime | None = None) -> None:
        """The probed panels of the scope, from what each project's last probe measured (none: not probed yet)."""
        got = [self.probes[p.name] for p in self.found if p.name in self.probes]
        new = self._probed_content(got, now) if got else {}  # built first, then swapped in: a draw never sees them gone
        oldest = min(g["at"] for g in got) if got else None
        self.panel_at.update(dict.fromkeys(new, oldest))  # the time of the data shown
        with self.lock:
            for name in PROBE_PANELS:
                self.panels.pop(name, None)
            self.panels.update(new)
        self.probed_at = oldest if got and not self.needs_probe() else None

    def _probed_content(self, got: list[dict], now: datetime | None) -> dict[str, dict]:
        now = now or datetime.now(timezone.utc)
        only = None if self.every else {p.name for p in self.projs}
        return {"alerts": {"projects": [g["alerts"] for g in got]}, "audit": {"projects": [g["audit"] for g in got]},
                "health": {"projects": [g["health"] for g in got], "exec": perf_summary(only, now),
                           "reviews": review_summary(),
                           **({"probes": self.dep_probes} if self.dep_probes is not None else {})},
                "digest": {"projects": [g["digest"] for g in got]}}

    def refresh(self, probe: bool = False) -> set[str]:
        """One tick: the sessions (a transcript only when it changed), the file panels whose files changed (all of
        them the first time), then the probes when asked; the panels whose content changed, or whose read failed
        with a new error. A read that fails is never raised: its panels keep their last content, its error goes to
        ``errors`` (``snapshot``), and it is read again at the next tick (the probe, at the next probe)."""
        read, failed, self.dirty = set(self.dirty), set(), set()
        try:
            groups = self.changed()
            if "graph" in groups:
                self.read_graph()
            read |= self._read_ok({p for g in groups for p in FILE_PANELS[g]})
        except Exception as exc:  # shown in the panels, never fatal
            self.sigs.pop("graph", None)  # read again at the next tick
            failed |= self._failed(FILE_PANELS["graph"], exc)
        try:
            changed, had_error = self.read_sessions(), "sessions" in self.errors
            self._read_ok({"sessions"})
            if changed or had_error:
                read.add("sessions")
        except Exception as exc:  # the same
            failed |= self._failed(("sessions",), exc)
        if probe:
            try:
                self.probe()
                read |= self._read_ok({*PROBE_PANELS, "queue"})
            except Exception as exc:  # the same: probed again at the next probe
                failed |= self._failed(PROBE_PANELS, exc)
            finally:
                self.progress = None
        read |= self._read_plugged(probe, failed)
        if read:
            self.read_at = transcript.iso(datetime.now(timezone.utc))
        return read | failed

    def _read_plugged(self, probe: bool, failed: set) -> set[str]:
        """The plugins' panels read when first shown, then at each probe; a failed one added to ``failed``, its last
        content kept."""
        read = set()
        for name in [n for n in PLUGGED if probe or n not in self.plugged_tried]:
            self.plugged_tried.add(name)  # a failing read waits for the next probe, as the probed panels do
            try:
                self._set(**{name: self._plugged(name)})
                read |= self._read_ok({name})
            except Exception as exc:  # its last content kept, its error shown
                failed |= self._failed((name,), exc)
        return read

    def _plugged(self, name: str) -> dict:
        """A plugged panel's rows for the projects of the scope its plugin belongs to (brain.plugin_panels.rows)."""
        p = PLUGGED[name]
        return {"projects": [{"project": x.name, "rows": plugin_panels.rows(p, x)}
                             for x in self.found if x.name == p.project]}

    def _read_ok(self, panels) -> set[str]:
        at = transcript.iso(datetime.now(timezone.utc))
        for p in panels:
            self.panel_at[p] = at
            self.errors.pop(p, None)
        return set(panels)

    def _failed(self, panels, exc: Exception) -> set[str]:
        """The panels' read failed: its error and time (the first failure's while the same error goes on); the
        panels whose error is new, to draw again (the same error again changes nothing on screen)."""
        error = {"at": transcript.iso(datetime.now(timezone.utc)), "error": f"{type(exc).__name__}: {exc}"}
        new = set()
        for p in panels:
            old = self.errors.get(p)
            if old and old["error"] == error["error"]:
                continue
            self.errors[p] = error
            new.add(p)
        return new

    def snapshot(self) -> dict:
        with self.lock:
            panels = dict(self.panels)
        return {"cockpit": 1, "scope": self.scope,
                "projects": [{"name": p.name, "root": str(p.root), "found": p.root.is_dir()} for p in self.projs],
                "read_at": self.read_at, "probed_at": self.probed_at, "panels": panels, "registry": self.registry,
                "errors": dict(self.errors), "panel_at": dict(self.panel_at),
                "probing": dict(self.progress) if self.progress else None}


# --- the view: filters, sort and search over the table panels ---

SORTS = {"sessions": ("state", "age", "project", "context", "cost", "ctx", "role"),
         "queue": ("band", "score", "unblocks", "age", "kind", "project"),
         "frontier": ("priority", "score", "unblocks", "milestone", "age", "project")}
FILTERS = {"sessions": {"state": ("open", ALL, *STATES)},  # open: not ended
           "queue": {"kind": (ALL, *queue.KINDS), "band": (ALL, *queue.BANDS)},
           "frontier": {"priority": (ALL, "P0-P1", "P0-P2", "none"), "milestone": (ALL, "none")}}
OPEN_VALUES = {("frontier", "milestone")}  # any milestone id too: the panel's own (choices)
SORT_COLUMNS = {"sessions": {"State": "state", "Last": "age", "Project": "project", "Context": "context", "Ctx": "ctx",
                             "Role": "role", "Cost": "cost"},
                "queue": {"Band": "band", "Score": "score", "Unblocks": "unblocks", "Age": "age", "Kind": "kind",
                          "Project": "project"},
                "frontier": {"P": "priority", "Score": "score", "Unblocks": "unblocks", "Milestone": "milestone",
                             "Age": "age",
                             "Project": "project"}}


def _age_first(days) -> int:
    return -(days if days is not None else -1)  # the oldest first, an unknown age last


SORT_KEYS = {
    "sessions": {"state": lambda r: (STATES.index(r["state"]), r["age_s"]), "age": lambda r: r["age_s"],
                 "project": lambda r: (r["project"], STATES.index(r["state"]), r["age_s"]),
                 "context": lambda r: -(r.get("context") or 0),
                 "ctx": lambda r: (r.get("ctx_pct") is None, -(r.get("ctx_pct") or 0), r["age_s"]),
                 "role": lambda r: (("master", "relay", "sub", "solo").index(r.get("role") or "solo"), r["age_s"]),
                 "cost": lambda r: (r.get("cost_usd") is None, -(r.get("cost_usd") or 0), r["age_s"])},
    "queue": {"band": lambda e: (queue.BANDS.index(e.get("band") or "later"), e.get("order") is None,
                                 e.get("order") or 0, -(e.get("score") or 0), -e.get("unblocks", 0)),
              # the highest score first (one without a score last), then what it unblocks, then the oldest
              "score": lambda e: (e.get("score") is None, -(e.get("score") or 0), -e.get("unblocks", 0),
                                  e.get("since") or "9999"),
              "unblocks": lambda e: (-e.get("unblocks", 0), not e.get("blocking"), e.get("since") or "9999"),
              "age": lambda e: (_age_first(e.get("age_days")), -e.get("unblocks", 0)),
              "kind": lambda e: (e.get("kind") or "", e.get("category") or "", -e.get("unblocks", 0)),
              "project": lambda e: (e["project"], -e.get("unblocks", 0))},
    # the rank of brain next (brain.ranking): priority, the owner's order, then value over effort
    "frontier": {"priority": lambda i: (*_rank(i["priority"]), _order(i), -(i.get("score") or 0)),
                 "score": lambda i: (-(i.get("score") or 0), *_rank(i["priority"])),
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
    key = "rows" if name in PLUGGED else {"queue": "entries", "frontier": "items", "milestones": "pending",
                                          "alerts": "alerts"}[name]
    return [{**r, "project": g["project"]} for g in panel.get("projects") or [] for r in g.get(key) or []]


def _keep_plugged(name: str, r: dict, v: dict) -> bool:
    """A plugin's filters: the field's value as its cell shows it."""
    return all(v[f] in (ALL, plugin_panels.cell(r.get(f))) for f in FILTERS[name])


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
    if name in PLUGGED:
        return " ".join([r["project"], r["id"], *(plugin_panels.cell(r.get(k)) for k, _ in PLUGGED[name].columns)]
                        ).lower()
    keys = {"sessions": ("session_id", "host_id", "name", "role", "parent_name", "project", "state", "step", "title",
                         "branch", "model"),
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
        keep = _keep_plugged if name in PLUGGED else _keep
        rows = [r for r in rows if keep(name, r, v)]
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


# --- the states: why a panel is empty, what a panel not probed waits for (wi-brain-tui-states) ---

NOTHING = {"sessions": "No session wrote its transcript in the last {hours:g} h",
           "queue": "Nothing waits on {owner} in {scope}",
           "alerts": "No open alert in {scope}",
           "milestones": "No pending milestone in {scope}",
           "frontier": "No startable item in {scope}"}
EMPTY_COLUMN = {"sessions": "Title", "queue": "What", "alerts": "Message", "milestones": "Title", "frontier": "Title"}


def span(seconds: float) -> str:
    """A countdown: 45 s, 1 min 40, 2 h 05."""
    s = max(0, round(seconds))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min" + (f" {s % 60:02d}" if s % 60 else "")
    return f"{s // 3600} h {s % 3600 // 60:02d}"


def probe_wait(progress: dict | None, seconds: float | None = None, paused: bool = False) -> str:
    """What a panel not probed yet waits for: the probe running (``progress``: what it reads, project n of total),
    paused, or due in ``seconds`` (None: at the next tick)."""
    if progress:
        n = f" {progress['n']}/{progress['total']}" if progress.get("n") else ""
        return f"probing: {progress['what']}{n}"
    if paused:
        return "not probed yet: paused (space resumes, r probes now)"
    if seconds is None or seconds < 1:
        return "not probed yet: the probe starts at the next tick"
    return f"not probed yet: probe in {span(seconds)} (r for now)"


def _scope_text(scope: str) -> str:
    return "every project" if scope == ALL else scope


def why_empty(name: str, snap: dict, view: dict | None = None, search: str = "", wait: str = "") -> str:
    """Why a table panel of ``snap`` shows no row ('' when it shows one): not read or not probed yet (``wait``, as
    ``probe_wait`` says it), its first read failed, a filter or the search hides its rows (and the key that changes
    it), or nothing in the scope (and the projects of the scope this machine lacks)."""
    panel = (snap.get("panels") or {}).get(name)
    if panel is None:
        return _why_no_panel(name, snap, wait)
    if shown(name, panel, view, search):
        return ""
    every = entries(name, panel)
    return _why_hidden(name, len(every), view, search) if every else _why_nothing(name, panel, snap)


def _why_no_panel(name: str, snap: dict, wait: str) -> str:
    error = (snap.get("errors") or {}).get(name)
    if error:
        return f"read failed: {error['error']}"
    return (wait or "not probed yet") if name in PROBE_PANELS else "not read yet"


def _why_hidden(name: str, total: int, view: dict | None, search: str) -> str:
    """All ``total`` rows hidden: by which filters and search, and the key that changes each."""
    v = view_of(name, view) if view is not None and name in SORTS else None
    hides = [f"{f} {v[f]}" for f in FILTERS[name] if v[f] != ALL] if v else []
    keys = ["f changes the filters"] if hides else []
    if search.strip():
        hides.append(f"search '{search.strip()}'")
        keys.append("Escape clears the search")
    return f"{total} hidden by {', '.join(hides)}: {', '.join(keys)}"


def _why_nothing(name: str, panel: dict, snap: dict) -> str:
    """No row at all: nothing in the scope, and the projects of the scope this machine lacks."""
    missing = [p for p in snap.get("projects") or [] if not p.get("found", True)]
    text = NOTHING[name].format(owner=config.name_of(), scope=_scope_text(snap.get("scope", "")),
                                hours=panel.get("hours", HOURS))
    return text + "".join(f"; {p['name']} is not on this machine ({p['root']})" for p in missing)


def scope_choices(choices: dict) -> list[tuple[str, str, bool]]:
    """The project selector's options: (label, value, on this machine), global first; a project the registry names
    but this machine lacks keeps its place, labelled so (the TUI greys it)."""
    out = [("global: every project", ALL, True)]
    for name, p in choices.items():
        found = p is not None and Path(p.root).is_dir()
        out.append((name if found else f"{name} (not on this machine)", name, found))
    return out


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
    "sessions": {"what": "The sessions whose transcript was written in the last --hours (24): state, session (its short "
                         "name, else the app's id; both ids in the detail), role (master, sub, relay, solo), parent, "
                         "kids live/started, project, step n/m of its plan, model, effort, Ctx (% of its budget; a "
                         "master's row yellow, orange, red at 70, 80, 90 %), context used and its budget, output "
                         "tokens, last write, title or branch. asking: a question to {owner} or a blocked wrap-up; running; stale: nothing "
                         "written for 15 min; idle: its turn ended; ended: the SessionEnd hook recorded its end.",
                 "from": "the transcripts' tails, the SR snapshots of the Stop hook (~/.brain/sessions/<id>.json), "
                         "the desktop app's session files (a closed list of keys) and the SessionStart events, "
                         "the plans (the PostToolUse hook's <id>.plan.json, else the transcript's plan calls), the "
                         "ledger's SessionEnd events",
                 "read": "every --refresh (2 s), a transcript only when it changed",
                 "detail": "brain sessions show ID (its family, report and what a message would meet); the "
                           "session's own transcript"},
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
                       "code index, audit debt above its written view, alert events and alert files, a dependency "
                       "probe not OK.",
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
                         "and milestones it unblocks, and the age of its idea; the column chooser adds its size, "
                         "value and score (value over effort, brain next --explain), and the default order is brain "
                         "next's: priority, the owner's order, then the score.",
                 "from": "the graph (brain.status.frontier, brain.cockpit.frontier_rows)",
                 "read": "when a graph file changes",
                 "detail": "research_graph work-frontier; brain item set <id> priority=P1"},
    "audit": {"what": "The audit debt: the findings by severity and repo, the first P0 and P1 ones.",
              "from": "brain.status.audit_of, as brain audit (every repo of the project)",
              "read": "at each probe",
              "detail": "brain audit --project <p>"},
    "health": {"what": "Each stack's and each code index repo's state, this machine's dependency probes (a login, a "
                       "tool's last output, an index's or a backup's age), the exec-time ledger's last 7 days "
                       "(runs, failures, regressions), and the review error score (findings per PR, per wave, and "
                       "whether the reviews may lighten).",
               "from": "brain.status.probed, as brain health and brain index; brain.depprobes, as brain probes; "
                       "brain.perf; brain.review.score, as brain review score",
               "read": "at each probe",
               "detail": "brain health; brain index; brain probes; brain perf"},
    "digest": {"what": "The journals' last day and the records, then the latest written digest, else last week's built "
                       "offline.",
               "from": "brain.status.records_of, brain.digest",
               "read": "at each probe",
               "detail": "brain digest; brain resume"},
    "exec": {"what": "The execution-time ledger's last 7 days: runs and failures, the slowest steps by their median, the "
                     "regressions.",
             "from": "brain.perf, as brain perf",
             "read": "at each probe",
             "detail": "brain perf"},
    "settings": {"what": "Each setting, its value, the file or variable it comes from and how it changes, page by page "
                         "(the pages on the left): Cockpit, the screen's own settings in tui.json (theme, timezone, "
                         "language, refresh and probe intervals, each panel's free title), edited here with Enter; "
                         "Identity, Brain and Permissions, the brain's settings, each changed only by the command it "
                         "names; Setup, the commands that set a brain up, one per step. A secret is named, never shown.",
                 "from": "brain.settings: tui.json, config.json, projects.yaml, the profile (brain.tiers), "
                         "permissions.yaml and the environment, read when the tab opens and on r",
                 "read": "when the tab opens, after an edit and on r",
                 "detail": "brain tui --once --tab settings"},
    "overview": {"what": "One card per tab: what counts in it, at a glance. Enter or a click opens that tab, already "
                         "filtered as its card says (band now, the sessions asking), whatever the owner's filters and "
                         "search; a filter that is never saved and goes when the tab is left. v shows the grid of every "
                         "panel (not on a narrow terminal), then the digest.",
                 "from": "the panels already read, nothing more",
                 "read": "as its panels are",
                 "detail": "brain tui --once --tab overview"},
}


def help_lines(name: str) -> list[str]:
    """A panel's help: what it shows, where it comes from, how often it is read, the commands for the detail, and
    its keys. ``{owner}`` in a text is config.json's owner."""
    h = {k: v.replace("{owner}", config.name_of()) for k, v in HELP[name].items()}
    keys = ("s next sort, o reverse, f filters and sort, a column title sorts; " if name in SORTS else "")
    keys += "C its columns; " if name in COLUMNS else ""
    if name == "overview":
        return [h["what"], "", f"From: {h['from']}.", f"Read: {h['read']}.", f"Detail: {h['detail']}.", "",
                "Keys: Enter or a click opens a card's tab, the arrows move between the cards, v the next view, a tab's "
                "key goes straight to it."]
    return [h["what"], "", f"From: {h['from']}.", f"Read: {h['read']}.", f"Detail: {h['detail']}.", "",
            f"Keys: {keys}/ search, {TABS[panel_tab(name)]['key']} opens its tab, m full view where a tab shows several "
            "panels, Escape back to the overview."]


# --- the screen's remembered state: <BRAIN_HOME>/tui.json ---

def state_path() -> Path:
    return paths.brain_home() / STATE_FILE


def load_state(path: Path | None = None) -> dict:
    """The scope, the panels' views, the last tab and each tab's view, each table's columns and the settings (``theme``,
    ``tz``, ``lang``, ``titles``, ``refresh`` and ``probe`` in seconds) the interactive cockpit last showed; {} without them (the file missing, unreadable or not this shape). A tab,
    a view or a column this engine does not have is left out. Read-only: an unreadable file is not moved (the next
    :func:`save_state` sets it aside), and one a newer brain wrote is read as it is."""
    st = stateio.load(path or state_path(), known=STATE_V, aside=False)
    data = st.data if st.status in ("ok", "newer") else {}
    out: dict = {}
    if isinstance(data.get("scope"), str) and data["scope"]:
        out["scope"] = data["scope"]
    if isinstance(data.get("panels"), dict):
        out["panels"] = {n: view_of(n, v) for n, v in data["panels"].items() if n in SORTS and isinstance(v, dict)}
    out.update(_saved_tabs(data))
    out.update(_saved_columns(data))
    if isinstance(data.get("settings"), dict):
        got = data["settings"]
        out["settings"] = {k: got[k] for k in ("theme", "tz", "lang") if isinstance(got.get(k), str) and got[k]
                           and (k != "tz" or got[k] in TZS) and (k != "lang" or got[k] in LANGS)}
        out["settings"].update({k: float(got[k]) for k in ("refresh", "probe")   # seconds (the Settings tab)
                                if type(got.get(k)) in (int, float) and INTERVAL_MIN <= got[k] <= INTERVAL_MAX})
        if isinstance(got.get("titles"), dict):
            titles = {k: v.strip() for k, v in got["titles"].items()
                      if k in (*PANELS, *FRAMES, *PLUGGED) and isinstance(v, str) and v.strip()}
            if titles:
                out["settings"]["titles"] = titles
    return out


def state_refusal(path: Path | None = None) -> str:
    """Why :func:`save_state` will not write tui.json ('' when it will): a newer brain wrote it, or it cannot be read
    at all. (One of the wrong shape is set aside by the save, which then writes.)"""
    st = stateio.load(path or state_path(), known=STATE_V, aside=False)
    return st.refusal() if st.refused else ""


def _known_keys() -> dict:
    """The keys of tui.json this engine knows, by level (None: a value it owns whole); every other key is kept."""
    return {"cockpit": None, "scope": None, "tab": None, "panels": dict.fromkeys(SORTS), "tabs": dict.fromkeys(TABS),
            "columns": dict.fromkeys(COLUMNS),
            "settings": {"theme": None, "tz": None, "lang": None, "refresh": None, "probe": None,
                         "titles": dict.fromkeys((*PANELS, *FRAMES, *PLUGGED))}}


def _unknown(old: dict, known: dict) -> dict:
    """The parts of ``old`` whose keys ``known`` does not name, at every level it names."""
    out = {}
    for k, v in old.items():
        if k not in known:
            out[k] = v
        elif isinstance(known[k], dict) and isinstance(v, dict):
            sub = _unknown(v, known[k])
            if sub:
                out[k] = sub
    return out


def _merged(base: dict, top: dict) -> dict:
    out = dict(base)
    for k, v in top.items():
        out[k] = _merged(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _saved_columns(data: dict) -> dict:
    """Each table's chosen columns in a saved state: those it has, and a title width it offers."""
    saved = data.get("columns")
    out = {}
    for name, c in (saved if isinstance(saved, dict) else {}).items():
        if name not in COLUMNS or not isinstance(c, dict):
            continue
        given = c.get("shown") if isinstance(c.get("shown"), list) else []
        shown = list(dict.fromkeys(x for x in given if isinstance(x, str) and x in every_column(name)))
        width = c.get("width") if type(c.get("width")) is int and c.get("width") in TITLE_WIDTHS else 0
        if shown or width:
            out[name] = {"shown": shown, "width": width}
    return {"columns": out} if out else {}


def _saved_tabs(data: dict) -> dict:
    """The last tab and each tab's view of a saved state, those this engine has."""
    out: dict = {"tab": data["tab"]} if data.get("tab") in built_tabs() else {}
    if isinstance(data.get("tabs"), dict):
        out["tabs"] = {t: {"view": v["view"]} for t, v in data["tabs"].items()
                       if t in TABS and isinstance(v, dict) and isinstance(v.get("view"), str)
                       and v["view"] in TABS[t]["views"]}
    return out


# --- the panels' titles: the owner's display name, the language, a free title per panel (wi-brain-owner-label) ---

LANGS = ("en", "fr")
TITLES = {"sessions": "Sessions", "alerts": "Alerts", "milestones": "Milestones", "frontier": "Frontier",
          "audit": "Audit debt", "health": "Stacks and index", "digest": "Digest", "exec": "Exec times"}
QUEUE_TITLES = {"en": ("{name}'s queue", "My queue"), "fr": ("File de {name}", "Ma file")}  # (named, unnamed)
_VOWELS = "aeiouyàâäéèêëîïôöûùü"
_settings_cache: dict = {}


def settings() -> dict:
    """tui.json's settings (theme, tz, lang, titles), read again only when the file changed: its modification time
    and its size (Windows stamps times from a coarse clock, so two writes in a row can share one), and after each
    :func:`save_state` of this process."""
    path = state_path()
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
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
    own = PLUGGED[name].title[lang()] if name in PLUGGED else None
    return (settings().get("titles") or {}).get(name) or own or (queue_title() if name == "queue" else TITLES[name])


def save_state(state: dict, path: Path | None = None) -> bool:
    """Written whole through brain.stateio (a backup, then an atomic write), the keys this engine does not know kept
    from the file on disk; False when it could not be (a newer brain's file, an OSError; never raised)."""
    path = path or state_path()
    try:
        st = stateio.load(path, known=STATE_V)
        if not st.writable:
            return False
        stateio.save(st, _merged(_unknown(st.data, _known_keys()), {"cockpit": 1, **state}), indent=1)
    except (OSError, stateio.StateError):
        return False
    _settings_cache.clear()  # settings() reads the new file, whatever its time says
    return True


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


def session_text(r: dict) -> str:
    """The Session column (ST-2): the short name, else the app's id, else the transcript's; the ids in the detail."""
    return r.get("name") or sessions.short(r.get("host_id") or "") or r["session_id"][:8]


def kids_text(r: dict) -> str:
    return f"{r.get('kids_live', 0)}/{r['kids']}" if r.get("kids") else "-"


def ctx_text(r: dict) -> str:
    return f"{r['ctx_pct']:.0f} %" if r.get("ctx_pct") is not None else "-"


def model_text(r: dict) -> str:
    return str(r.get("model") or "-").removeprefix("claude-")


def session_lines(panel: dict, width: int = WIDTH, view: dict | None = None, search: str = "") -> list[str]:
    rows = panel.get("rows") or []
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in STATES}
    lines = [_noted(f"{title('sessions')} ({len(rows)} in the last {panel.get('hours', HOURS):g} h"
                    + "".join(f", {n} {s}" for s, n in counts.items() if n) + ")", "sessions", panel, view, search)]
    rows = shown("sessions", panel, view, search)
    if rows:
        lines.append("  state    session        role   parent         kids  project    model    effort ctx   "
                     "context   out      last  step | title")
    for r in rows:
        head = (f"  {r['state']:<8} {session_text(r)[:14]:<14} {str(r.get('role') or 'solo'):<6} "
                f"{str(r.get('parent_name') or '-')[:14]:<14} {kids_text(r):<5} {r['project'][:10]:<10} "
                f"{model_text(r)[:8]:<8} {str(r.get('effort') or '-')[:6]:<6} {ctx_text(r):<5} {context_text(r):<9} "
                f"{tokens(r['output_tokens']):<5} {ago(r['age_s']):>7}  ")
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
    if panel.get("defaulted"):
        lines.append(f"  {panel['defaulted']}")
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


def _last_ok_text(iso: str | None, now: datetime) -> str:
    if not iso:
        return ""
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f"last OK {ago((now - t).total_seconds())}" + (" ago" if (now - t).total_seconds() >= 60 else "")


def _states(rows, what: str, now: datetime | None = None) -> str:
    if isinstance(rows, dict):
        return f"error: {rows.get('error')}"
    if not rows:
        return f"no {what} declared"
    now = now or datetime.now(timezone.utc)
    bad = [r for r in rows if r.get("state") != "OK"]

    def why(r):
        parts = [p for p in (r.get("why"), _last_ok_text(r.get("last_ok"), now)) if p]
        return f" ({'; '.join(parts)})" if parts else ""
    return f"{len(rows) - len(bad)} of {len(rows)} OK" + "".join(
        f"; {r.get('name') or r.get('repo')} {r['state']}{why(r)}" for r in bad)


def health_lines(panel: dict | None, width: int = WIDTH, now: datetime | None = None) -> list[str]:
    if not panel:
        return [f"{title('health')}: not probed yet"]
    lines = [title("health")]
    for g in panel.get("projects") or []:
        lines.append(_line("  ", f"{g['project']}: stacks {_states(g['stacks'], 'stack', now)}; code index "
                                 f"{_states(g['code_index'], 'repo', now)}", width))
    probes_ = panel.get("probes") or {}
    if probes_.get("probes") or probes_.get("errors"):
        from . import depprobes
        lines.append(_line("  ", f"dependency probes: {depprobes.status_line(probes_)}", width))
    lines += review_lines(panel.get("reviews"), width)
    ex = panel.get("exec") or {}
    if ex:
        reg = "; ".join(f"{r['task']} +{r['change']:.0%}" for r in ex.get("regressions") or [])
        lines.append(_line("  ", f"exec ledger: {ex['runs']} run(s) in {ex['days']} d, {ex['failed']} failed, "
                                 f"{len(ex.get('regressions') or [])} regression(s)" + (f": {reg}" if reg else ""),
                           width))
    return lines


def review_lines(rv: dict | None, width: int = WIDTH) -> list[str]:
    """The health tab's line of the review error score (review_summary), none before a PR is reviewed."""
    if not rv or not rv["total"]["prs"]:
        return []
    trend = ", ".join(f"{w['wave']} {w['per_pr']}" for w in rv["waves"])
    verdict = "the reviews may lighten" if rv["lighten"]["ok"] else "the reviews stay complete"
    return [_line("  ", f"review error score: {rv['total']['per_pr']} confirmed finding(s) per PR over "
                        f"{rv['total']['prs']} PR(s)" + (f"; per wave {trend}" if trend else "") + f"; {verdict}",
                  width)]


def exec_lines(panel: dict | None, width: int = WIDTH) -> list[str]:
    """The health tab's exec frame, from the health panel: its runs and failures, the slowest steps by their median
    (each one's runs, failures and longest), the regressions."""
    if not panel:
        return [f"{title('exec')}: not probed yet"]
    ex = panel.get("exec") or {}
    if not ex:
        return [title("exec"), "  no run read"]
    lines = [f"{title('exec')} ({ex['runs']} run(s) in {ex['days']} d, {ex['failed']} failed)"]
    for r in ex.get("slowest") or []:
        failed = f", {r['failed']} failed" if r.get("failed") else ""
        lines.append(_line("  ", f"{r['median_s']:g} s (max {r['max_s']:g} s, {r['runs']} run(s){failed}) "
                                 f"{r['project']}: {r['task']}", width))
    lines += [_line("  ", f"regression: {r['task']} +{r['change']:.0%}", width) for r in ex.get("regressions") or []]
    return lines


def digest_lines(panel: dict | None, width: int = WIDTH, lines_max: int = 12, titled: bool = True) -> list[str]:
    """The digest panel's text: its first ``lines_max`` lines per project (0: all of them). ``titled`` False: under a
    frame that says Digest already, no « Digest » on each project's line and no first heading of the digest itself."""
    if not panel:
        return [f"{title('digest')}: not probed yet"]
    lines = []
    for g in panel.get("projects") or []:
        rec = g["records"]
        journal = "; ".join(f"{Path(j['path']).name} {j['last'] or 'no entry'}" for j in rec.get("journals") or [])
        r = rec.get("records") or {}
        lines.append(f"{'Digest ' if titled else ''}{g['project']} "
                     f"({g['digest']}{', written' if g['written'] else ', built offline'}); "
                     f"journal {journal or '-'}" + (f"; {r['ddr']} DDR, {r['sr']} SR, {r['ar']} AR" if r else ""))
        body = [x for x in g["text"].splitlines() if x.strip()]
        if not titled and body and body[0].startswith("# Digest"):
            body = body[1:]
        lines += [_line("  ", x, width) for x in body[:lines_max or None]]
        if lines_max and len(body) > lines_max:
            lines.append(f"  ... {len(body) - lines_max} more line(s) (brain digest)")
    return lines or ["Digest: no project found"]


# --- the TUI's tables: plain strings, one tuple per row ---

COLUMNS = {
    "sessions": ("State", "Session", "Role", "Parent", "Kids", "Project", "Step", "Model", "Effort", "Ctx", "Context",
                 "Out", "Last", "Title"),
    "queue": ("Band", "Score", "Unblocks", "Kind", "Project", "Age", "What", "Id"),
    "alerts": ("Level", "Project", "Key", "Since", "Message"),
    "milestones": ("Project", "Done", "Progress", "Milestone", "Title"),
    "frontier": ("P", "Project", "Unblocks", "Milestone", "Age", "Id", "Title"),
}
# offered by the column chooser, hidden by default
EXTRA_COLUMNS = {"sessions": ("Cost", "App id", "Id", "Branch"), "frontier": ("Size", "Value", "Score")}
TITLE_WIDTHS = (0, 40, 60, 80, 100)  # the longest a table's title may be, the rest in the detail; 0: no limit


def _days_text(days) -> str:
    return f"{days} d" if days is not None else "-"


def every_column(name: str) -> tuple[str, ...]:
    """All a table can show: its default columns, then those the column chooser offers."""
    return COLUMNS[name] + EXTRA_COLUMNS.get(name, ())


def cells(name: str, r: dict, project: bool = True, tz: str | None = None, chosen: dict | None = None) -> tuple[str, ...]:
    """One record of a table panel (an item of ``entries``) as its row, ``columns(name, project, chosen)``; its times in
    ``tz`` (None: as recorded, UTC); its title cut to ``chosen``'s width."""
    row = dict(zip(every_column(name), (*_cells(name, r, tz), *_extra_cells(name, r))))
    width = (chosen or {}).get("width")
    if width:
        row[EMPTY_COLUMN[name]] = _cut(row[EMPTY_COLUMN[name]], width)
    return tuple(row[c] for c in columns(name, project, chosen))


def _extra_cells(name: str, r: dict) -> tuple[str, ...]:
    if name == "sessions":
        return (usage.usd(r.get("cost_usd")), sessions.short(r.get("host_id") or "") or "-", r["session_id"][:8],
                r.get("branch") or "-")
    if name == "frontier":   # brain.ranking's parts: brain next --explain
        return (r.get("size") or "-", (r.get("value") or "-") + (" (quick win)" if r.get("quick_win") else ""),
                f"{r['score']:g}" if r.get("score") is not None else "-")
    return ()


def _cells(name: str, r: dict, tz: str | None = None) -> tuple[str, ...]:
    if name in PLUGGED:
        return (r["project"], *(plugin_panels.cell(r.get(k)) for k, _ in PLUGGED[name].columns or (("id", "Id"),)))
    if name == "sessions":
        return (r["state"], session_text(r), r.get("role") or "solo", r.get("parent_name") or "-", kids_text(r),
                r["project"], r["step"] or "-", model_text(r), str(r.get("effort") or "-"), ctx_text(r),
                context_text(r), tokens(r["output_tokens"]), ago(r["age_s"]), r["title"] or r["branch"])
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


def columns(name: str, project: bool = True, chosen: dict | None = None) -> tuple[str, ...]:
    """A table's columns, as ``chosen`` orders them (``{"shown": [...], "width": n}``; none, or none left: the default);
    without the project column when the scope holds one project."""
    shown = [c for c in (chosen or {}).get("shown") or () if c in every_column(name) and (project or c != "Project")]
    return tuple(shown) or tuple(c for c in COLUMNS[name] if project or c != "Project")


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
             "frontier": frontier_lines, "audit": audit_lines, "health": health_lines, "exec": exec_lines}
    if name == "digest":
        return title("digest") if panel else f"{title('digest')}: not probed yet"
    if name in PLUGGED:
        return f"{title(name)} ({len(entries(name, panel))})" if panel else f"{title(name)}: not read yet"
    if name in TABS and name not in lines:  # a tab's own help (the overview's cards)
        return tab_title(name)
    return lines[name](panel if name in PROBE_PANELS else panel or {})[0]


# --- the tabs: one per question the owner asks (wi-brain-tui-layout, spec cockpit-ux-round2 §4.0, UX-18) ---

NARROW_COLUMNS, NARROW_ROWS = 120, 30  # under either: the tabs alone, the grid not offered, the bar's numbers (UX-2)
DETAIL_COLUMNS = 140  # from here the detail sits right of the list (UX-20)
TAB_PADDING = 2  # a tab's padding in the bar, in columns
CARD_LINES = 4  # a card's lines at most (UX-19: 3 to 5, with its frame)
CARD_ORDER = ("queue", "sessions", "milestones", "frontier", "health", "resources", "lessons", "ideas", "features")
VIEW_LABELS = {"cards": {"en": "Cards", "fr": "Cartes"}, "grid": {"en": "Grid", "fr": "Grille"},
               "digest": {"en": "Digest", "fr": "Digest"},
               "list": {"en": "List", "fr": "Liste"}, "frames": {"en": "Frames", "fr": "Cadres"},
               "pages": {"en": "Pages", "fr": "Pages"}}


def _alerts_open(panels: dict) -> str:
    n = len(entries("alerts", panels.get("alerts")))
    return str(n) if n else ""


def _queue_now(panels: dict) -> str:
    n = sum(1 for e in entries("queue", panels.get("queue")) if e.get("band") == "now")
    return str(n) if n else ""


def _sessions_asking(panels: dict) -> str:
    n = sum(1 for r in entries("sessions", panels.get("sessions")) if r["state"] == "asking")
    return f"{n}!" if n else ""


def _card(tab: str, head: str, lines: list[str], foot: str = "", filters: dict | None = None) -> dict:
    """A tab's card: ``{tab, title, lines, foot, filters}``; ``filters``: {panel: {field: value}}, what it opens with."""
    return {"tab": tab, "title": f"{TABS[tab]['key']} {head}", "lines": [" ".join(x.split()) for x in lines][:CARD_LINES],
            "foot": foot, "filters": filters or {}}


def _counted(head: str, n: int, word: str) -> str:
    return f"{head} · {n} {word}" if n else head


def _summary(counts: dict[str, int]) -> list[str]:
    """One line: « 1 this week · 2 when you can », what has a count; none without one."""
    words = [f"{n} {word}" for word, n in counts.items() if n]
    return [" · ".join(words)] if words else []


def _queue_card(snap: dict, wait: str = "") -> dict:
    rows = shown("queue", (snap.get("panels") or {}).get("queue"), view_of("queue"))
    now = [e for e in rows if e.get("band") == "now"]
    bands = {queue.BAND_NAMES[b]: sum(e.get("band") == b for e in rows) for b in queue.BANDS if b != "now"}
    lines = [e["title"] for e in (now or rows)[:CARD_LINES - 1]] + _summary(bands)
    opens = ("Enter: the queue, band now", {"queue": {"kind": ALL, "band": "now"}}) if now else ("Enter: the queue", {})
    return _card("queue", _counted(title("queue"), len(now), "now"), lines or [why_empty("queue", snap)], *opens)


def _session_line(r: dict) -> str:
    what = r["title"] or r["step"] or r["branch"]
    return ("! " if r["state"] == "asking" else "") + session_text(r) + (f": {what}" if what else "")


def _sessions_card(snap: dict, wait: str = "") -> dict:
    rows = entries("sessions", (snap.get("panels") or {}).get("sessions"))
    asking = [r for r in rows if r["state"] == "asking"]
    states = {s: sum(r["state"] == s for r in rows) for s in STATES if s not in ("asking", "ended")}
    top = asking or [r for r in rows if r["state"] == "running"]
    lines = [_session_line(r) for r in top[:CARD_LINES - 1]] + _summary(states)
    opens = ("Enter: the sessions asking", {"sessions": {"state": "asking"}}) if asking else ("Enter: the sessions", {})
    return _card("sessions", _counted(title("sessions"), len(asking), "asking"),
                 lines or ([f"{len(rows)} ended"] if rows else [why_empty("sessions", snap)]), *opens)


def _milestones_card(snap: dict, wait: str = "") -> dict:
    panel = (snap.get("panels") or {}).get("milestones") or {}
    rows = sorted(entries("milestones", panel), key=lambda m: -(m["done"] / m["items"] if m["items"] else 0))
    lines = [f"{short_milestone(m['id'], m['project'])} {m['done']}/{m['items']} {bar(m['done'], m['items'])}"
             for m in rows[:CARD_LINES - 1]]
    reached = sum(g.get("reached", 0) for g in panel.get("projects") or [])
    lines += [f"{reached} reached"] if reached else []
    return _card("milestones", _counted(title("milestones"), len(rows), "pending"),
                 lines or [why_empty("milestones", snap)], "Enter: the milestones")


def _frontier_card(snap: dict, wait: str = "") -> dict:
    rows = shown("frontier", (snap.get("panels") or {}).get("frontier"), view_of("frontier"))
    lines = [f"{r['priority'] or '-'} {r['id'].removeprefix('wi-').removeprefix(r['project'] + '-')}: unblocks "
             f"{r.get('unblocks', 0)}" for r in rows[:CARD_LINES]]
    return _card("frontier", _counted(title("frontier"), len(rows), "startable"),
                 lines or [why_empty("frontier", snap, view_of("frontier"))], "Enter: the frontier")


def _health_card(snap: dict, wait: str = "") -> dict:
    panels = snap.get("panels") or {}
    alerts_ = sorted(entries("alerts", panels.get("alerts")), key=lambda a: -alerts.RANK.get(a["level"], 0))  # the worst
    unread = [f"{g['project']}: error: {g['error']}" for g in (panels.get("alerts") or {}).get("projects") or []
              if "error" in g]
    lines = (unread + [f"{a['level']} {a['message']}" for a in alerts_])[:CARD_LINES - 1] or [
        why_empty("alerts", snap, wait=wait)]
    quiet_ = quiet.line(quiet.summary())   # brain quiet: held, not paused (brain.quiet)
    if quiet_:
        lines = [quiet_] + lines[:CARD_LINES - 2]
    audit_ = [f"audit {g['project']}: {_counts(g['counts'])}" for g in (panels.get("audit") or {}).get("projects") or []
              if "counts" in g]
    return _card("health", _counted(tab_title("health"), len(alerts_), "alert(s)"), lines + audit_[:1], "Enter: health")


# key: 0 to 9 or a comma. views: {view: its panels, in the order they show}, the default first; none: not built yet, its
# key waits for it (arrives: what brings it). count: what the bar says of the tab, from the panels. card: its card in the
# overview.
TABS = {
    "overview": {"key": "0", "label": {"en": "Overview", "fr": "Vue d'ensemble"},
                 "question": {"en": "What waits on me, at a glance?", "fr": "Qu'est-ce qui m'attend, d'un coup d'œil ?"},
                 "views": {"cards": (), "grid": PANELS, "digest": ("digest",)}},
    "queue": {"key": "1", "label": {"en": "Queue", "fr": "File"},
              "question": {"en": "What must I decide or do?", "fr": "Que dois-je décider ou faire ?"},
              "views": {"list": ("queue",)}, "count": _queue_now, "card": _queue_card},
    "sessions": {"key": "2", "label": {"en": "Sessions", "fr": "Sessions"},
                 "question": {"en": "Who is working, who waits on me?", "fr": "Qui travaille, qui m'attend ?"},
                 "views": {"list": ("sessions",)}, "count": _sessions_asking, "card": _sessions_card},
    "frontier": {"key": "3", "label": {"en": "Frontier", "fr": "Frontier"},
                 "question": {"en": "What can start?", "fr": "Que peut-on démarrer ?"},
                 "views": {"list": ("frontier",)}, "card": _frontier_card},
    "milestones": {"key": "4", "label": {"en": "Milestones", "fr": "Jalons"},
                   "question": {"en": "Where are we going, and when?", "fr": "Où va-t-on, et quand ?"},
                   "views": {"list": ("milestones",)}, "card": _milestones_card},
    "ideas": {"key": "5", "label": {"en": "Ideas", "fr": "Idées"},
              "question": {"en": "What waits upstream?", "fr": "Qu'est-ce qui attend en amont ?"},
              "views": {}, "arrives": "the ideas board"},
    "lessons": {"key": "6", "label": {"en": "Lessons", "fr": "Leçons"},
                "question": {"en": "What did we learn, what came of it?", "fr": "Qu'a-t-on appris, qu'en a-t-on fait ?"},
                "views": {}, "arrives": "the lessons registry"},
    "features": {"key": "7", "label": {"en": "Features", "fr": "Features"},
                 "question": {"en": "What can the brain do, where are the gaps?",
                              "fr": "Que sait faire le Brain, où sont les trous ?"},
                 "views": {}, "arrives": "the capability graph"},
    "health": {"key": "8", "label": {"en": "Health", "fr": "Santé"},
               "question": {"en": "What is breaking or getting worse?", "fr": "Qu'est-ce qui casse ou se dégrade ?"},
               "views": {"frames": ("alerts", "audit", "health", "exec")}, "count": _alerts_open, "card": _health_card},
    "resources": {"key": "9", "label": {"en": "Resources", "fr": "Ressources"},
                  "question": {"en": "What does what runs cost?", "fr": "Que coûte ce qui tourne ?"},
                  "views": {}, "arrives": "the resources view"},
    "settings": {"key": ",", "label": {"en": "Settings", "fr": "Réglages"},
                 "question": {"en": "How are the cockpit and the brain set?",
                              "fr": "Comment le cockpit et le Brain sont-ils réglés ?"},
                 "views": {"pages": ("settings",)}},
}


def built_tabs() -> tuple[str, ...]:
    """The tabs the bar shows: those that have a view."""
    return tuple(n for n, t in TABS.items() if t["views"])


def not_built(name: str) -> str:
    """What a key says of a tab not built yet."""
    return f"{tab_title(name)} is not here yet: it arrives with {TABS[name]['arrives']}"


def narrow(columns: int, rows: int) -> bool:
    return columns < NARROW_COLUMNS or rows < NARROW_ROWS


def tab_title(name: str) -> str:
    """A tab's name: the queue's title (the owner's display name); a tab that is one panel of its name takes that panel's
    free title (tui.json settings.titles.<panel>); else its label in the cockpit's language."""
    if name == "queue":
        return title("queue")
    free = (settings().get("titles") or {}).get(name) if tab_panels(name) == (name,) else None
    return free or TABS[name]["label"][lang()]


def tab_question(name: str) -> str:
    return TABS[name]["question"][lang()]


def tab_count(name: str, snap: dict) -> str:
    """What the bar says of a tab, in digits and signs: the queue's band now, the sessions asking (``!``), the open
    alerts; '' when there is nothing to say."""
    count = TABS[name].get("count")
    return count(snap.get("panels") or {}) if count else ""


def tab_label(name: str, snap: dict) -> str:
    """A tab's entry in the bar: its key, its name and its count."""
    count = tab_count(name, snap)
    return " ".join(x for x in (TABS[name]["key"], tab_title(name), count) if x)  # a plugin's tab: no key


def tab_labels(snap: dict, active: str, columns: int, rows: int) -> dict[str, str]:
    """The bar: each built tab's entry; when the terminal is narrow or they do not fit, each tab's key alone, the active
    tab keeping its name and its count (``0  1 Queue 3  2  3  4  8``)."""
    full = {n: tab_label(n, snap) for n in built_tabs()}
    if not narrow(columns, rows) and sum(len(x) + TAB_PADDING for x in full.values()) <= columns:
        return full
    return {n: x if n == active else TABS[n]["key"] or x for n, x in full.items()}  # a plugin's tab: its name


def tab_views(name: str, is_narrow: bool = False) -> tuple[str, ...]:
    """A tab's views, the default first; the grid is not offered on a narrow terminal (UX-2)."""
    return tuple(v for v in TABS[name]["views"] if not (is_narrow and v == "grid"))


def tab_view(name: str, saved: str | None = None, is_narrow: bool = False) -> str:
    """The view a tab shows: ``saved`` when it is still offered, else its first."""
    views = tab_views(name, is_narrow)
    return saved if saved in views else views[0]


def tab_panels(name: str, view: str | None = None) -> tuple[str, ...]:
    """The panels and frames a tab's view shows, in order; those of all its views when ``view`` is None."""
    if view is not None:
        return TABS[name]["views"][view]
    return tuple(dict.fromkeys(p for panels in TABS[name]["views"].values() for p in panels))


def panel_tab(panel: str) -> str:
    """The tab that opens a panel or a frame: the one that holds it, the overview for the digest."""
    return next((n for n, t in TABS.items() if n != "overview" and any(panel in ps for ps in t["views"].values())),
                "overview")


def detail_beside(tab: str, view: str, columns: int) -> bool:
    """Whether a row's detail sits beside the list (UX-20): wide enough, on a view that is one table; else it opens over
    it."""
    panels = tab_panels(tab, view)
    return columns >= DETAIL_COLUMNS and len(panels) == 1 and panels[0] in COLUMNS


def card_tabs() -> tuple[str, ...]:
    """The tabs that have a card, in the overview's order: what waits on the owner first."""
    return tuple(n for n in CARD_ORDER if TABS[n]["views"] and TABS[n].get("card"))


def cards(snap: dict, wait: str = "") -> list[dict]:
    """The overview's cards (UX-19): each tab's title, lines, foot and the filters it opens with; ``wait``: what a panel
    not probed yet waits for, as ``probe_wait`` says it."""
    return [TABS[n]["card"](snap, wait) for n in card_tabs()]


def palette(choices: dict, is_narrow: bool = False) -> list[dict]:
    """The command palette's entries (spec cockpit-ux §4.4): every tab and view offered at this size, project, sort, filter
    and table's columns, each ``{title, help, do}``; ``do``: what brain.tui_palette runs, a tuple."""
    out = []
    for n in built_tabs():
        name = tab_title(n)
        out.append({"title": f"Go to {name}", "help": f"key {TABS[n]['key']}: {tab_question(n)}", "do": ("tab", n)})
        views = tab_views(n, is_narrow)
        out += [{"title": f"{name}: the {VIEW_LABELS[v][lang()]} view", "help": "v changes it", "do": ("view", n, v)}
                for v in views if len(views) > 1]
    out += [{"title": f"Project: {label}", "help": "p opens the selector", "do": ("scope", value)}
            for label, value, _ in scope_choices(choices)]
    for name in SORTS:
        out += [{"title": f"{title(name)}: sort by {key}", "help": "s changes it, o reverses it", "do": ("sort", name, key)}
                for key in SORTS[name]]
        out += [{"title": f"{title(name)}: {field} {value}", "help": "f holds its filters",
                 "do": ("filter", name, field, value)} for field, values in FILTERS[name].items() for value in values]
    out += [{"title": f"{title(name)}: choose its columns", "help": "C on its table", "do": ("columns", name)}
            for name in COLUMNS]
    out.append({"title": "Reset the views", "help": "every sort, filter, column and tab's view back to its default; the "
                                                    "project, the theme and the timezone stay", "do": ("reset",)})
    return out


def bar_status(changed: str | None, probe_in: float | None, probing: bool = False, paused: bool = False,
               tz: str | None = "local") -> str:
    """The global bar's right end: the last change and the next probe (``probe_in``: the seconds it is due in; None: at
    the next tick)."""
    probe = "probing" if probing else "paused" if paused else ("probe now" if probe_in is None or probe_in < 1
                                                               else f"probe in {span(probe_in)}")
    return f"changed {when(changed, tz, '%H:%M')} · {probe}"


def render(snap: dict, width: int = WIDTH, views: dict[str, dict] | None = None, search: str = "",
           tz: str | None = None, tab: str | None = None, root: Path | None = None) -> list[str]:
    """The text view: every panel, one after the other; ``views`` (each table panel's view, {} its defaults) and
    ``search`` narrow the sessions, the queue and the frontier (None: everything, in the panels' order); ``tz``
    shows the header's times in that timezone (None: as recorded, UTC); ``tab`` prints that tab's panels and frames
    alone, the overview's cards for the overview, the settings' pages for the settings (those of the brain at ``root``).
    The header names the installed version."""
    p = snap["panels"]

    def stamp(iso):
        return (f"{when(iso, tz, '%Y-%m-%d %H:%M:%S')} ({tz})" if iso else None) if tz else iso
    head = (f"brain {__version__} cockpit: {snap['scope']}; files read {stamp(snap.get('read_at')) or '-'}, probes "
            f"{stamp(snap.get('probed_at')) or 'not run'}")
    out = [head]
    if tab == "overview":
        for card in cards(snap, wait="not probed yet"):
            out += ["", card["title"], *(_line("  ", x, width) for x in card["lines"])]
        return out
    if tab == "settings":
        from . import settings as settings_
        return out + settings_.lines(settings_.collect(root), width)

    def v(name):
        return None if views is None else views.get(name, {})
    for name, lines in (("sessions", session_lines(p.get("sessions") or {}, width, v("sessions"), search)),
                        ("queue", queue_lines(p.get("queue") or {}, width, v("queue"), search)),
                        ("alerts", alert_lines(p.get("alerts"), width)),
                        ("milestones", milestone_lines(p.get("milestones") or {}, width)),
                        ("frontier", frontier_lines(p.get("frontier") or {}, width, view=v("frontier"), search=search)),
                        ("audit", audit_lines(p.get("audit"), width)), ("health", health_lines(p.get("health"), width)),
                        ("exec", exec_lines(p.get("health"), width)),
                        ("digest", digest_lines(p.get("digest"), width))):
        if name in (tab_panels(tab) if tab else PANELS):
            out += ["", *lines, *(_line("  ", s, width) for s in states(name, snap, v(name), search, tz))]
    return out + _plugged_text(snap, width, views, search, tz, tab)


def _plugged_text(snap: dict, width: int, views: dict | None, search: str, tz: str | None, tab: str | None) -> list:
    """The plugins' panels in the text view: with their tab, or with every panel."""
    out = []
    for name in PLUGGED:
        if name in (tab_panels(tab) if tab else PLUGGED):
            view = None if views is None else views.get(name, {})
            out += ["", *plugged_lines(name, snap["panels"].get(name), width, view, search),
                    *(_line("  ", s, width) for s in states(name, snap, view, search, tz))]
    return out


def plugged_lines(name: str, panel: dict | None, width: int = WIDTH, view: dict | None = None,
                  search: str = "") -> list[str]:
    """A plugin's panel in the text view: its heading, then its columns' titles and its rows, as its table shows them."""
    cols = columns(name)
    rows = [cells(name, r) for r in shown(name, panel, view, search)]
    widths = [max([len(c), *(len(r[i]) for r in rows)]) for i, c in enumerate(cols)]
    out = [_noted(heading(name, panel), name, panel, view, search)]
    out += [("  " + "  ".join(x.ljust(w) for x, w in zip(row, widths)).rstrip())[:width]  # aligned, never collapsed
            for row in ([cols] if rows else []) + rows]
    return out


# --- a plugged project's panels and tabs (brain.plugin_panels, wi-brain-command-plugins-cockpit) ---

PLUGGED: dict = {}      # <project>-<panel> -> plugin_panels.Panel
PLUG_NOTES: list = []   # what the plugins' declarations left out or tolerated
_TABLES = ("SORTS", "FILTERS", "SORT_KEYS", "SORT_COLUMNS", "COLUMNS", "EMPTY_COLUMN", "NOTHING", "HELP", "TITLES")


def plug(plugged: plugin_panels.Plugged) -> None:
    """The plugins' panels and tabs into the cockpit's tables, those of an earlier plug taken out first: each panel's
    columns (the project's first), sorts (then the project), filters, help and title, and each tab placed after
    Resources, before the settings, with no key."""
    for name in list(PLUGGED):
        for table in _TABLES:
            globals()[table].pop(name, None)
    PLUGGED.clear()
    PLUG_NOTES[:] = list(plugged.notes)
    for name, p in plugged.panels.items():
        _plug_panel(name, p)
    _plug_tabs(plugged.tabs)


def _plug_panel(name: str, p: plugin_panels.Panel) -> None:
    """One plugin panel's entries in each of the cockpit's tables."""
    PLUGGED[name] = p
    cols = p.columns or (("id", "Id"),)
    COLUMNS[name] = ("Project", *(t for _, t in cols))
    SORTS[name] = tuple(dict.fromkeys((*p.sorts, "project")))
    FILTERS[name] = dict(p.filters)
    SORT_KEYS[name] = {k: plugin_panels.sort_key(k) for k in SORTS[name]}
    SORT_COLUMNS[name] = {"Project": "project", **{t: k for k, t in cols if k in SORTS[name]}}
    EMPTY_COLUMN[name] = cols[-1][1]
    NOTHING[name] = f"No row of {p.project}'s plugin in {{scope}}"
    TITLES[name] = p.title["en"]
    HELP[name] = {"what": p.help or f"What {p.project}'s plugin shows: {p.title['en']}.",
                  "from": f"{p.project}'s plugin ({p.ref}): " + (f"the file {p.rows_file} under its root"
                                                                 if p.rows_file else f"{p.read}, given its root"),
                  "read": "at the cockpit's first read, then at each probe (--probe, 5 min, and r)",
                  "detail": f"brain {p.project} --help"}


def _plug_tabs(tabs: dict) -> None:
    """The plugins' tabs after Resources, before the settings, with no key; an earlier plug's taken out; one named as
    one of the cockpit's own tabs is noted and left out (its panels stay in the palette and --tab of their own)."""
    kept = [(n, t) for n, t in TABS.items() if not t.get("plugin")]
    PLUG_NOTES.extend(f"{t.project}: its tab {n} is one of the cockpit's own: left out" for n, t in tabs.items()
                      if n in dict(kept))
    at = next((i for i, (n, _) in enumerate(kept) if n == "settings"), len(kept))
    plugged_tabs = [(n, {"key": "", "label": t.label, "question": t.question, "views": {"list": t.panels},
                         "plugin": t.project}) for n, t in tabs.items() if n not in dict(kept)]
    TABS.clear()
    TABS.update(kept[:at] + plugged_tabs + kept[at:])


def plug_registry(root: Path | None = None) -> list[str]:
    """The plugins of the registry's projects plugged (``plug``); their notes. A registry that cannot be read plugs
    nothing."""
    try:
        reg = projects.load(root).values()
    except Exception as exc:  # no registry, or a broken one: the built-in panels alone
        plug(plugin_panels.Plugged())
        return [f"the plugins' panels are not read: {type(exc).__name__}: {exc}"]
    plug(plugin_panels.load(reg))
    return list(PLUG_NOTES)


def states(name: str, snap: dict, view: dict | None = None, search: str = "", tz: str | None = None) -> list[str]:
    """What the text view adds under a panel: its failed read (the error, and the time of the data still shown), and
    for a table panel that shows no row, why (``why_empty``; a panel not probed yet says so in its heading)."""
    panel, error = (snap.get("panels") or {}).get(name), (snap.get("errors") or {}).get(name)
    out = []
    if error and panel is not None:
        data_at = (snap.get("panel_at") or {}).get(name)
        out.append(f"read failed at {when(error['at'], tz)}: {error['error']}; data of {when(data_at, tz)}")
    if name in COLUMNS and (panel is not None or error or name not in PROBE_PANELS):
        why = why_empty(name, snap, view, search)
        out += [f"({why})"] if why else []
    return out


def watch(cp: Cockpit, refresh_s: float = REFRESH_S, probe_s: float = PROBE_S, out=None, ticks: int = 0,
          views: dict[str, dict] | None = None, search: str = "", tz: str | None = None,
          tab: str | None = None) -> int:
    """The text view redrawn in place when a panel changed (``brain tui --plain``, or no tui extra); Ctrl-C quits.
    ``views``, ``search``, ``tz`` and ``tab`` as ``render``'s. ``ticks``: stop after that many (tests)."""
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
                          + "\n".join(render(cp.snapshot(), width, views, search, tz, tab,
                                              getattr(cp, "root", None))) + "\n")
                out.flush()
            n += 1
            if ticks and n >= ticks:
                return 0
            time.sleep(refresh_s)
    except KeyboardInterrupt as exc:   # Ctrl+C quits; SIGTERM or a hang-up stops it as any command (brain.shutdown)
        if getattr(exc, "signum", signal.SIGINT) != signal.SIGINT:
            raise
        return 0
