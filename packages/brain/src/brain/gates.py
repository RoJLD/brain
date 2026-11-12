"""Gates as data (wi-brain-forecast-gates; spec-brain-psychohistory §3.4, spec-brain-sizing-prioritization §5.4,
spec-brain-product-lifecycle §3.4): what holds a node without being work, written so that ``brain forecast`` can
draw it, ``brain check`` can judge it and ``brain queue`` can count what it holds.

A WorkItem or a Milestone carries ``props.gate``: one gate or a list of them, each a mapping with a ``kind``:

  calendar  ``{kind: calendar, days: 28, from: <item id | YYYY-MM-DD>, resets: "a missed week", reset_daily: 0.02}``
            data to accumulate: ``days`` days counted from a date, from the end of an item, or from today without
            ``from``; ``resets`` says in words what starts the count again, ``reset_daily`` the chance a day does it
            (0 without it), which the forecast draws;
  count     ``{kind: count, of: ddr.answered, at_least: 100}``: a counter that must reach a value. The engine measures
            ``ddr.answered`` (the answered DDRs of records/ddr, their pace over the last ``PACE_DAYS`` days) and
            ``items.done`` (the store's done WorkItems, their pace from the store's history); any other counter
            gives its own ``current`` and ``per_day``;
  external  ``{kind: external, ref: <project>:<id>}``: another project's item (or this one's), passed once done;
  hardware  ``{kind: hardware, machine: <name>, ready: 2026-12..2027-01}``: a machine to come, ready on a day or
            within a range of days or months the owner gives; without ``ready``, not dated, and what waits on it
            neither;
  go_nogo   ``{kind: go_nogo, ddr: <id>}``: a stage or era exit, a Go/NoGo DDR posed once the node's dependencies are
            done (its exit evidence met); its delay is drawn from the owner's past answers; passed once that DDR is
            answered.

Two gates need no prop: a pending blocking DDR whose ``links.items`` names an item (a decision of the owner), and a
pending DDR of kind ``action`` that names one (an action only the owner may do), each drawn from the owner's past
answer delays of its kind (brain.forecast.decision_gates).

``props.due`` is a deadline, not a gate: a real external date only (a pilot, a legal step, hardware, a third party)
with its ``due_source``; the forecast alerts when an item's p80 passes it.

``brain check`` (``check_lines``) warns on a malformed gate, on a trigger that names a duration (days, weeks, in a
row) on a node without a gate, on an ``after_external`` that does not resolve to ``<project>:<id>`` (a registered
project, an id of its store), and on a ``due`` without its source.
"""

from __future__ import annotations

import calendar as _cal
import math
import re
from datetime import date, timedelta
from pathlib import Path

from . import graph, projects

KINDS = ("calendar", "count", "external", "hardware", "go_nogo")
COUNTERS = ("ddr.answered", "items.done")   # the counters the engine measures
PACE_DAYS = 28        # the days a measured counter's pace is taken over
MAX_DAYS = 3650
REF_RE = re.compile(r"^([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+)$")
_READY_RE = re.compile(r"^(\d{4}-\d{2}(?:-\d{2})?)(?:\s*\.\.\s*(\d{4}-\d{2}(?:-\d{2})?))?$")
DURATION_RE = re.compile(r"\b(?:\d+|one|two|three|four|five|six|seven|ten|thirty|sixty)\s+(?:days?|weeks?|months?)\b"
                         r"|\bin a row\b|\bconsecutive\b|\bcontinuous(?:ly)?\b", re.I)
OPEN = {"WorkItem": ("todo", "doing", "blocked"), "Milestone": ("pending",)}
LIST_MAX = 10


# --- reading ---

def of(props: dict | None) -> list[dict]:
    """The gates of a node's props: ``props.gate`` as a list of mappings (one mapping is a list of one)."""
    raw = (props or {}).get("gate")
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [g for g in raw if isinstance(g, dict)]
    return []


def parse_ref(text) -> tuple[str, str] | None:
    """(project, id) of ``<project>:<id>``, the first word of ``text``; None when it is not one."""
    words = str(text or "").split()
    m = REF_RE.match(words[0]) if words else None
    return (m.group(1), m.group(2)) if m else None


def _month_end(y: int, m: int) -> date:
    return date(y, m, _cal.monthrange(y, m)[1])


def ready_range(text) -> tuple[date, date] | None:
    """(first day, last day) of ``YYYY-MM[-DD][..YYYY-MM[-DD]]``: a month spans its days; None when unreadable."""
    m = _READY_RE.match(str(text or "").strip())
    if not m:
        return None
    try:
        a, b = m.group(1), m.group(2) or m.group(1)
        lo = date.fromisoformat(a) if len(a) == 10 else date.fromisoformat(a + "-01")
        hi = date.fromisoformat(b) if len(b) == 10 else _month_end(int(b[:4]), int(b[5:7]))
    except ValueError:
        return None
    return (lo, hi) if hi >= lo else None


def _day(text) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def problems(g: dict) -> list[str]:
    """What is wrong with one gate ('' list when it is well formed); the external ref is resolved apart."""
    kind = g.get("kind")
    if kind not in KINDS:
        return [f"kind {kind!r} is not one of {', '.join(KINDS)}"]
    out = []
    if kind == "calendar":
        if not (_num(g.get("days")) or 0) > 0:
            out.append("a calendar gate needs days: N (N > 0)")
        p = g.get("reset_daily")
        if p is not None and not (_num(p) is not None and 0 <= p < 1):
            out.append("reset_daily is a chance a day, 0 <= p < 1")
    elif kind == "count":
        if not g.get("of"):
            out.append("a count gate needs of: <counter>")
        if _num(g.get("at_least")) is None:
            out.append("a count gate needs at_least: N")
        if g.get("of") and g.get("of") not in COUNTERS and _num(g.get("per_day")) is None:
            out.append(f"the counter {g.get('of')!r} is not measured ({', '.join(COUNTERS)}): give current and per_day")
    elif kind == "external":
        if not parse_ref(g.get("ref")):
            out.append("an external gate needs ref: <project>:<id>")
    elif kind == "hardware":
        if not g.get("machine"):
            out.append("a hardware gate needs machine: <name>")
        if g.get("ready") is not None and not ready_range(g.get("ready")):
            out.append("ready is a day or a range YYYY-MM[-DD]..YYYY-MM[-DD]")
    return out


def label(g: dict) -> str:
    """'hardware gpu-box', 'calendar 28 days', 'external quant:wi-x', 'count ddr.answered >= 100', 'go/no-go'."""
    kind = g.get("kind")
    if kind == "calendar":
        return f"calendar {g.get('days')} days" + (f" from {g['from']}" if g.get("from") else "")
    if kind == "count":
        return f"count {g.get('of')} >= {g.get('at_least')}"
    if kind == "external":
        return f"external {g.get('ref')}"
    if kind == "hardware":
        return f"hardware {g.get('machine')}"
    if kind == "go_nogo":
        return "go/no-go" + (f" {g['ddr']}" if g.get("ddr") else "")
    return str(kind)


# --- resolving another project's item ---

class Resolver:
    """The status of ``<project>:<id>``, each project's store read once: '' when the project or the id is unknown."""

    def __init__(self, root: Path | None = None, here: tuple[str, dict] | None = None) -> None:
        self.root = root
        self.cache: dict[str, dict | None] = {}
        if here:
            self.cache[here[0]] = here[1]

    def _nodes(self, name: str) -> dict | None:
        if name not in self.cache:
            try:
                p = projects.load(self.root).get(name)
            except (SystemExit, OSError, ValueError):
                p = None
            store = next((s for s in p.stores if (s / "schema.yaml").is_file()), None) if p else None
            try:
                self.cache[name] = ({k: n for k, (_, n) in graph.node_index(store).items()} if store else None)
            except (OSError, ValueError):
                self.cache[name] = None
        return self.cache[name]

    def known(self, name: str) -> bool:
        return self._nodes(name) is not None

    def status(self, ref) -> str:
        pr = parse_ref(ref)
        nodes = self._nodes(pr[0]) if pr else None
        n = (nodes or {}).get(pr[1]) if pr else None
        return str(n.get("status") or "") if n else ""

    def why_not(self, ref) -> str:
        """Why ``ref`` does not resolve ('' when it does)."""
        pr = parse_ref(ref)
        if not pr:
            return "not <project>:<id>"
        if not self.known(pr[0]):
            return f"no registered project {pr[0]!r} with a store"
        return "" if self.status(ref) else f"no {pr[1]} in {pr[0]}'s store"


# --- the measured counters ---

def counter(name: str, ddrs: list[dict], work: list[dict], flow: dict, today: date) -> tuple[float, float] | None:
    """(current, per day) of a counter the engine measures; None for another one."""
    if name == "ddr.answered":
        days = [_day((d.get("answer") or {}).get("at")) for d in ddrs if (d.get("answer") or {}).get("at")]
        days = [d for d in days if d]
        since = today - timedelta(days=PACE_DAYS - 1)
        return float(len(days)), round(sum(1 for d in days if since <= d <= today) / PACE_DAYS, 4)
    if name == "items.done":
        return (float(sum(1 for n in work if n.get("status") == "done")),
                float(flow.get("closed_per_day") or 0.0))
    return None


# --- prepared for the futures ---

def prepare(g: dict, *, today: date, resolver: Resolver, nodes: dict, ddrs: list[dict], work: list[dict],
            flow: dict) -> dict:
    """One gate as the forecast draws it, plain data: ``{"label", "kind", ...}`` with ``passed`` (true: it holds
    nothing any more), ``undated`` (why the forecast cannot date it), or what to draw:

      ``{"days": d, "reset": p}``               a calendar count of d days left from now, a reset chance a day;
      ``{"after": item, "days": d, "reset": p}`` the same, counted from an item's end (a dependency with a lag);
      ``{"lo": a, "hi": b}``                    a day drawn uniformly between a and b days from now;
      ``{"decision": True}``                    a Go/NoGo once the node's dependencies are done (an answer delay)."""
    out = {"label": label(g), "kind": g.get("kind")}
    bad = problems(g)
    if bad:
        return {**out, "undated": f"a malformed gate: {bad[0]}"}
    kind = g["kind"]
    if kind == "calendar":
        days, reset = float(g["days"]), float(g.get("reset_daily") or 0.0)
        src = g.get("from")
        start = _day(src) if src and _day(src) else None
        if src and not start:
            n = nodes.get(str(src))
            if not n:
                return {**out, "undated": f"calendar from an unknown item: {src}"}
            if n.get("status") != "done":
                return {**out, "after": str(src), "days": days, "reset": reset}
            start = _day((n.get("props") or {}).get("done")) or today
        left = max(0.0, days - ((today - start).days if start else 0))
        return {**out, "passed": True} if not left else {**out, "days": left, "reset": reset}
    if kind == "count":
        measured = counter(g["of"], ddrs, work, flow, today)
        current = _num(g.get("current"))
        per_day = _num(g.get("per_day"))
        if measured:
            current = measured[0] if current is None else current
            per_day = measured[1] if per_day is None else per_day
        left = float(g["at_least"]) - (current or 0.0)
        if left <= 0:
            return {**out, "passed": True}
        if not per_day or per_day <= 0:
            return {**out, "undated": f"a count without a pace: {g['of']} {current or 0:g} of {g['at_least']}"}
        d = left / per_day
        return {**out, "lo": d, "hi": d} if d <= MAX_DAYS else \
            {**out, "undated": f"a count beyond ten years: {g['of']}"}
    if kind == "external":
        st = resolver.status(g["ref"])
        if st in ("done",):
            return {**out, "passed": True}
        why = resolver.why_not(g["ref"])
        return {**out, "undated": f"after another project: {g['ref']}" + (f" ({why})" if why else f" ({st})")}
    if kind == "hardware":
        rng = ready_range(g.get("ready"))
        if not rng:
            return {**out, "undated": f"hardware not dated: {g['machine']}"}
        lo, hi = (rng[0] - today).days, (rng[1] - today).days + 1
        return {**out, "passed": True} if hi <= 0 else {**out, "lo": max(0, lo), "hi": max(0, hi)}
    # go_nogo
    ddr = next((d for d in ddrs if d.get("id") == g.get("ddr")), None) if g.get("ddr") else None
    if ddr and ddr.get("status") != "pending" and (ddr.get("answer") or {}).get("at"):
        return {**out, "passed": True}
    return {**out, "decision": True}


def draw(p: dict, rng, delays_h: list[float]) -> tuple[float, float]:
    """One future's draw of a prepared gate: (release in calendar days from now, lag in days after the node's
    dependencies). A gate that passed or cannot be dated draws (0, 0): the plan keeps an undated one out."""
    if p.get("passed") or p.get("undated"):
        return 0.0, 0.0
    if p.get("decision"):
        return 0.0, (rng.choice(delays_h) / 24 if delays_h else 0.0)
    if "lo" in p:
        return (p["lo"] + rng.random() * (p["hi"] - p["lo"])), 0.0
    days, reset = p["days"], p.get("reset") or 0.0
    t = days
    if reset > 0:   # a reset day starts the count again: draw the day of each reset until a count gets through
        t, k = 0.0, days
        while t < MAX_DAYS:
            u = rng.random()
            first = math.floor(math.log(1 - u) / math.log(1 - reset)) if u > 0 else math.inf  # days before a reset
            if first >= k:
                t += k
                break
            t += first + 1
            k = days
        t = min(t, MAX_DAYS)
    return (0.0, t) if p.get("after") else (t, 0.0)


# --- brain check ---

def _ids(ids: list[str]) -> str:
    more = f" and {len(ids) - LIST_MAX} more" if len(ids) > LIST_MAX else ""
    return ", ".join(ids[:LIST_MAX]) + more


def check_lines(store: Path, root: Path | None = None, resolver: Resolver | None = None) -> list[str]:
    """``brain check``'s warnings about gates and deadlines on the open items and pending milestones."""
    index = {k: n for k, (_, n) in graph.node_index(store, generated=False).items()}
    nodes = [n for n in index.values() if n.get("status") in OPEN.get(n.get("type"), ())]
    resolver = resolver or Resolver(root)
    malformed, timed, external, unresolved, undue = [], [], [], [], []
    for n in sorted(nodes, key=lambda x: x["id"]):
        props = n.get("props") or {}
        gs = of(props)
        if props.get("gate") is not None and not gs:
            malformed.append(f"{n['id']} (gate is not a mapping or a list of them)")
        for g in gs:
            bad = problems(g)
            if bad:
                malformed.append(f"{n['id']} ({bad[0]})")
            elif g.get("kind") == "external":
                why = resolver.why_not(g["ref"])
                if why:
                    external.append(f"{n['id']} ({g['ref']}: {why})")
            elif g.get("kind") == "calendar" and g.get("from") and not _day(g["from"]) and \
                    str(g["from"]) not in index:
                malformed.append(f"{n['id']} (calendar from {g['from']}: no such item)")
        words = sorted({w.group(0).lower() for w in DURATION_RE.finditer(str(props.get("trigger") or ""))})
        if words and not gs:
            timed.append(f"{n['id']} ({', '.join(words)})")
        if props.get("after_external"):
            why = resolver.why_not(props["after_external"])
            if why:
                unresolved.append(f"{n['id']} ({why})")
        if props.get("due") is not None and not props.get("due_source"):
            undue.append(n["id"])
    lines = []
    if malformed:
        lines.append(f"warning: {len(malformed)} malformed gate(s) (docs/gates.md): {_ids(malformed)}")
    if timed:
        lines.append(f"warning: {len(timed)} trigger(s) name a duration with no gate (props.gate {{kind: calendar, "
                     f"days: N}}, docs/gates.md): {_ids(timed)}")
    if external:
        lines.append(f"warning: {len(external)} external gate(s) that do not resolve: {_ids(external)}")
    if unresolved:
        lines.append(f"warning: {len(unresolved)} after_external that do not resolve to <project>:<id> (or a gate "
                     f"{{kind: external, ref: <project>:<id>}}): {_ids(unresolved)}")
    if undue:
        lines.append(f"warning: {len(undue)} due date(s) without their source (props.due_source: the pilot, a legal "
                     f"step, hardware, a third party): {_ids(undue)}")
    return lines
