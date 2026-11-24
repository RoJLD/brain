"""``brain forecast``: when each milestone and the whole backlog will be done, as ranges, at zero token
(wi-brain-backlog-forecast; spec-brain-psychohistory §4.1, §4.4 and §6; the owner, 2026-11-02, PSY-2 and PSY-5: a
calibrated Monte Carlo, ``brain forecast`` in text first).

A Monte Carlo of futures over the project's open work items. Each future draws, in this order:

  error      a shared estimate-error factor F: one quantile of the backtests' ratios actual / estimate of the active
             time (brain.cost.backtests), the class's own ratios once it has ``CLASS_MIN`` of them, else every item's.
             Estimates err together; drawn apart, the errors cancel out and the range narrows to a false precision;
  durations  each item's active hours from a lognormal fitted on the median and p25-p75 of its most alike finished
             items (brain.cost.raw_estimate), times F; its cost the same way, with the same draw; an item in progress
             keeps the draw minus what its sessions spent, at least ``REMAIN_MIN`` of it;
  capacity   the active hours a day of the sessions that served one of the project's items, drawn by blocks of up to
             a week from the last ``CAPACITY_DAYS`` days (a day without one counts, as zero), shared by lanes: the
             parallel sessions of a past day (its active hours over the hours a session was open, at most its peak);
  scope      an item whose priority is only proposed stays with the keep rate of the store's proposals (kept: validated
             or done; against dropped);
  gates      an item a pending blocking DDR names starts once the owner answers, after a delay drawn from their past answers;
             one a pending action DDR names (what only the owner may do), after a delay drawn from the actions done;
             the gates written on a node (props.gate, brain.gates: calendar, count, external, hardware, go_nogo) each
             draw a release day or a lag after its dependencies; a milestone's own gate holds its finish. An item
             blocked, with an external blocker, after another project's item not done, after a deferred one or behind
             a gate the forecast cannot date (hardware without a ready range, a count without a pace) is not dated,
             nor is what waits on it: listed apart, with the milestone triggers that name a duration and no gate. An
             item whose p80 passes its ``due`` date raises an alert.

An event-queue scheduler gives each free lane the ready item first by the owner's priority (in progress first, then P0
to P3, a validated priority before a proposed one), then their order (``props.order``, lower first), then the default
score of COST-5 (``SCORE``: value over effort). It returns each item's finish, a milestone's is its items' latest.

Out, from ``RUNS`` futures: p10, p50, p80 and p90 per item, per milestone and for the whole backlog, the work left
(hours and USD), and the honesty bar of PSY-2:
  - each number says its nature: (s) measured, (d) derived by the simulation, (e) estimated;
  - a date is a range p10-p90; the p50 is shown alone only once calibrated: ``CALIBRATED_MIN`` reached milestones
    judged against the snapshot taken before them, their coverage within ``COVERAGE_TOL`` of ``COVERAGE``;
  - beyond ``HORIZON_DAYS`` days, no date: the order, the work left and the gates;
  - no date for the whole backlog while it grows faster than it empties (items created against closed a day, from
    the store's git history); its frozen scope is shown apart;
  - the deferred items (the icebox, SB-12) stay out of every date and are shown apart (if everything thawed), as is
    the inflow; what is not modelled is said (risks, declared absences, the quota cap, other projects).

``--json`` is reproducible: the seed, the futures, the inputs' digests (the store's commit and files, the model's
inputs, the settings) and the code's version; the same inputs and seed give the same characters. Each run keeps its
result in ``<BRAIN_HOME>/forecast/<project>/latest.json`` (what ``brain status --quick`` reads); ``brain cost audit
--write``, the Monday task's command, writes the week's snapshot ``<BRAIN_HOME>/forecast/<project>/<day>.json``, which
the calibration judges once milestones are reached.

An item may be part of several milestones (wi-brain-forecast-two-parents): its row keeps its thematic milestone
(``milestone``: the first of its milestones that is not of kind wave, an era included), its wave (``wave``: the first of
kind wave) and every one (``parents``), additive keys of ``FORMAT`` 1. « (no milestone) » counts the open items with no
thematic milestone, a wave's alone included; a milestone's own range reads its members (``Store.milestone_items``).

What the scheduler knows is kept (wi-brain-forecast-starts-critical, ``MODEL_V`` 3, additive keys of ``FORMAT`` 1):
each dated item's ``start`` (p10-p90 days and dates), its drawn ``hours`` and its ``critical`` index per group it is a
member of (its milestones, its wave, ``*`` the backlog, ``""`` no milestone): the share of futures in which it lies on
the chain that sets that group's finish (Van Slyke 1963). The chain of a future is followed back from the group's last
item to end, each link what let the next one start (``by``: ``now``, ``gate``, ``dependency``, or ``lane``, the item
whose end freed the lane it waited for); a group's ``chain`` is its most frequent one, with each item's index, the
share of futures it was that chain and the share whose finish the milestone's own gate set. ``past``: the ledger's
first session, done day and active hours of each done or doing member of an open milestone (the past bars of the
cockpit's item level). ``brain forecast --critical [<milestone>]`` prints the chains (``critical_lines``).
"""

from __future__ import annotations

import bisect
import hashlib
import heapq
import importlib
import json
import math
import random
import re
import subprocess
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import __version__, config, cost, diffs, graph, paths, projects, ranking, records, resume, waves
from . import gates as gate_data

FORMAT = 1            # the JSON's layout
MODEL_V = 3           # the method's version: a snapshot says which one made it (2: declared gates; 3: the starts,
#                       the criticality index and the chains, the past; additive keys, FORMAT 1 kept)
RUNS = 1000
STATUS_RUNS = 300     # brain status' futures
SEED = 1              # the default seed: the same inputs give the same numbers
CAPACITY_DAYS = 28    # the past days the capacity is drawn from
BLOCK_DAYS = 7        # by blocks of up to a week (spec 4.1)
FLOW_DAYS = 28        # the days the inflow and the outflow are measured over
HORIZON_DAYS = 42     # beyond six weeks, no date (PSY-2)
CALIBRATED_MIN = 5    # reached milestones judged before the label says calibrated
COVERAGE, COVERAGE_TOL = 0.80, 0.15
CLASS_MIN = 5         # backtests a class needs for an error factor of its own
REMAIN_MIN = 0.2      # an item in progress has at least this share of its draw left
SIGMA_MIN = 0.15      # the narrowest lognormal of an item
MAX_DAYS = 3650       # a future not done in ten years stops there
INVALID_SCOPE = 0.20  # a saved forecast is invalidated once the open items moved by more (PSY-2, point 6)
QUANTILES = (("p10", 0.1), ("p50", 0.5), ("p80", 0.8), ("p90", 0.9))
# The default score (COST-5) that orders the items the owner's priority and order leave tied: value / effort, value
# = base + the value of the features the item delivers + the milestone it moves + the open items it unblocks, effort
# = its estimated active hours here (brain next's rank, brain.ranking, which owns SCORE, takes it from the size). A
# written setting, not a hidden constant (spec 4.3).
SCORE = ranking.SCORE
PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
DEFERRED = "deferred"
CLOSED = ("done", "dropped")
NOT_MODELLED = ("risks (wi-brain-risk-register)", "the owner's declared absences and weekly decision budget "
                "(wi-brain-capacity-model)", "the quota as a cap on capacity", "other projects' dates "
                "(wi-brain-scope-rollups)", "the inflow")
_DURATION_RE = gate_data.DURATION_RE   # a trigger's duration words: a calendar gate the store has not written
_LINE_RE = re.compile(r"^\+- \{id: ([\w.-]+), type: WorkItem, status: (\w+)")


class ForecastError(RuntimeError):
    pass


# --- the inputs ---

def _ts(text) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")) if text else None
    except ValueError:
        return None


def _day(text) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, timeout=60)
    if res.returncode:
        raise ForecastError(res.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed")
    return res.stdout.decode("utf-8", "replace")


def flow(store: Path, today: date) -> dict:
    """The work items created and closed (done or dropped) a day over the last ``FLOW_DAYS`` days, from the store's
    git history (the first-parent chain: on main, the day a PR landed); {"days": 0} outside git. A node's first line
    (``- {id: X, type: WorkItem, status: S``) dates its creation and its closing; a store written another way is read
    by the engine's timeline (research_graph.history), slower."""
    try:
        top = Path(_git(store, "rev-parse", "--show-toplevel").strip())
        rel = Path(store).resolve().relative_to(top.resolve()).as_posix()
        log = _git(top, *diffs.argv("log", "--first-parent", "--reverse", "-p", "-U0", "--format=%x00%cI",
                                    "--", f"{rel}/nodes" if rel != "." else "nodes"))
    except (ForecastError, OSError, ValueError, subprocess.TimeoutExpired):
        return {"days": 0, "created": 0, "closed": 0}
    created: dict[str, date] = {}
    closed: dict[str, date] = {}
    first, day, matched = None, None, False
    for when, files in diffs.log_records(log):   # brain.diffs: the engine's one reader
        ts = _ts(when)
        day = ts.astimezone(timezone.utc).date() if ts else day
        first = first or day
        for line in diffs.lines(files, "+"):
            m = _LINE_RE.match(line)
            if m and day:
                matched = True
                nid, status = m.groups()
                created.setdefault(nid, day)
                if status in CLOSED:
                    closed.setdefault(nid, day)
    if not matched and first:
        created, closed = _timeline_flow(store)
    if not first:
        return {"days": 0, "created": 0, "closed": 0}
    start = max(first, today - timedelta(days=FLOW_DAYS - 1))
    days = (today - start).days + 1
    n_in = sum(1 for d in created.values() if start <= d <= today)
    n_out = sum(1 for d in closed.values() if start <= d <= today)
    return {"days": days, "since": start.isoformat(), "created": n_in, "closed": n_out,
            "created_per_day": round(n_in / days, 2), "closed_per_day": round(n_out / days, 2),
            "growing": n_in > n_out, "start": first.isoformat()}


def _timeline_flow(store: Path) -> tuple[dict, dict]:
    from research_graph import history  # the engine; only for a store not written one node a line

    created, closed = {}, {}
    for e in history.timeline(store, types={"WorkItem"}):
        if e.kind == "created":
            created.setdefault(e.id, e.commit.when.astimezone(timezone.utc).date())
        if e.kind in ("created", "status") and e.new in CLOSED:
            closed.setdefault(e.id, e.commit.when.astimezone(timezone.utc).date())
    return created, closed


def capacity(rows: list[dict], start: date, today: date) -> dict:
    """{days: [{day, hours, lanes}], ...}: each day of [start, today] (at most ``CAPACITY_DAYS``), the active hours of
    the sessions that served one of the scope's items (a session's active time shared among its days by their
    messages), and its lanes: the active hours over the hours one such session was open, at least 1, at most the
    peak of sessions open together."""
    start = max(start, today - timedelta(days=CAPACITY_DAYS - 1))
    hours = {start + timedelta(days=k): 0.0 for k in range((today - start).days + 1)}
    spans: dict[date, list[tuple[datetime, datetime]]] = {d: [] for d in hours}
    for r in rows:
        if not r.get("served"):
            continue
        per = {_day(d): (v.get("messages") or 0) for d, v in (r.get("days") or {}).items()}
        n = sum(per.values())
        for d, m in per.items():
            if d in hours:
                hours[d] += (r.get("active_s") or 0) / 3600 * (m / n if n else 1 / len(per))
        a, b = _ts(r.get("start")), _ts(r.get("end"))
        if a and b and b > a:
            for d in spans:
                lo = max(a, datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
                hi = min(b, datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1))
                if hi > lo:
                    spans[d].append((lo, hi))
    days = []
    for d in sorted(hours):
        open_h, peak = _open_hours(spans[d])
        lanes = max(1, min(peak, round(hours[d] / open_h))) if open_h and hours[d] else 0
        days.append({"day": d.isoformat(), "hours": round(hours[d], 3), "lanes": lanes})
    return {"days": days, "since": start.isoformat()}


def _open_hours(spans: list[tuple[datetime, datetime]]) -> tuple[float, int]:
    """(hours at least one span is open, the most spans open together)."""
    ev = sorted([(a, 1) for a, _ in spans] + [(b, -1) for _, b in spans], key=lambda x: (x[0], x[1]))
    cur = peak = 0
    total, since = 0.0, None
    for t, k in ev:
        if cur == 0 and k > 0:
            since = t
        cur += k
        peak = max(peak, cur)
        if cur == 0 and since is not None:
            total += (t - since).total_seconds() / 3600
            since = None
    return total, peak


def _ddrs(root: Path) -> list[dict]:
    yaml = graph._yaml()
    out = []
    for f in sorted((root / records.RECORDS_DIR / "ddr").glob("*.yaml")):
        try:
            d = graph.load_yaml_file(f)
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(d, dict) and d.get("id"):
            out.append(d)
    return out


def decision_gates(root: Path, ddrs: list[dict] | None = None) -> tuple[dict[str, list[str]], list[float]]:
    """({item: [the pending blocking DDRs naming it]}, the hours the owner took to answer each answered DDR)."""
    gates: dict[str, list[str]] = {}
    delays = []
    for d in _ddrs(root) if ddrs is None else ddrs:
        asked, answer = _ts((d.get("asked") or {}).get("at")), _ts((d.get("answer") or {}).get("at"))
        if asked and answer and answer >= asked:
            delays.append(round((answer - asked).total_seconds() / 3600, 3))
        if d.get("status") == "pending" and d.get("blocking"):
            for i in (d.get("links") or {}).get("items") or []:
                gates.setdefault(str(i), []).append(d["id"])
    return gates, sorted(delays)


def action_gates(ddrs: list[dict]) -> tuple[dict[str, list[str]], list[float]]:
    """({item: [the pending DDRs of kind action naming it]}: what only the owner may do, a gate whether or not it is
    flagged blocking; the hours the owner took to do each action done (asked to answered))."""
    gates: dict[str, list[str]] = {}
    delays = []
    for d in ddrs:
        if (d.get("kind") or "decision") != "action":
            continue
        asked, answer = _ts((d.get("asked") or {}).get("at")), _ts((d.get("answer") or {}).get("at"))
        if asked and answer and answer >= asked:
            delays.append(round((answer - asked).total_seconds() / 3600, 3))
        if d.get("status") == "pending":
            for i in (d.get("links") or {}).get("items") or []:
                gates.setdefault(str(i), []).append(d["id"])
    return gates, sorted(delays)


def keep_rate(work: list[dict]) -> dict:
    """The share of proposals the owner kept: an item validated (props.validated) or done with a proposed priority only,
    against one dropped without a validation; (kept + 1) / (resolved + 2), so that no count gives 0 or 1."""
    kept = dropped = 0
    for n in work:
        p = n.get("props") or {}
        if p.get("validated") or (n.get("status") == "done" and p.get("priority_proposed") and not p.get("priority")):
            kept += 1
        elif n.get("status") == "dropped" and not p.get("validated"):
            dropped += 1
    return {"kept": kept, "dropped": dropped, "rate": round((kept + 1) / (kept + dropped + 2), 4)}


def _priority(props: dict) -> tuple[str, bool]:
    """(P0..P3 or '', proposed): the owner's priority, else the proposed one."""
    p = str(props.get("priority") or "").strip()
    if p in PRIORITY_RANK:
        return p, False
    q = str(props.get("priority_proposed") or "").strip()
    return (q, True) if q in PRIORITY_RANK else ("", True)


def _lognormal(q: dict | None, scale: float = 1.0) -> tuple[float, float] | None:
    """(mu, sigma) of the lognormal whose median and p25-p75 are ``q``'s (times ``scale``)."""
    if not q or not q.get("median"):
        return None
    med = max(q["median"] * scale, 1e-6)
    lo, hi = max((q.get("p25") or med) * scale, 1e-6), max((q.get("p75") or med) * scale, 1e-6)
    return math.log(med), max((math.log(hi) - math.log(lo)) / (2 * 0.6745), SIGMA_MIN)


def _store_digest(store: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(store.rglob("*.yaml")):
        h.update(f.relative_to(store).as_posix().encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return "sha256:" + h.hexdigest()[:16]


def _digest(data) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                                 default=str).encode()).hexdigest()[:16]


def settings() -> dict:
    return {"model": MODEL_V, "capacity_days": CAPACITY_DAYS, "block_days": BLOCK_DAYS, "flow_days": FLOW_DAYS,
            "horizon_days": HORIZON_DAYS, "class_min": CLASS_MIN, "remain_min": REMAIN_MIN, "sigma_min": SIGMA_MIN,
            "calibrated_min": CALIBRATED_MIN, "coverage": COVERAGE, "coverage_tol": COVERAGE_TOL, "score": SCORE}


def _part_of_milestones(nodes: dict[str, dict], edges: list[dict], items) -> dict[str, set[str]]:
    """{item: the Milestones it is part of}, for each of ``items`` that is part of one."""
    by: dict[str, set[str]] = {}
    for e in edges:
        if e.get("type") == "part_of" and e.get("from") in items and (nodes.get(e.get("to")) or {}).get(
                "type") == "Milestone":
            by.setdefault(e["from"], set()).add(e["to"])
    return by


def _parents(nodes: dict[str, dict], edges: list[dict], items) -> dict[str, dict]:
    """{item: {milestone, wave, parents}}: the Milestones each of ``items`` is part of, its thematic one (the first by
    id not of kind wave: an era counts) and its wave apart, so an item in both keeps both. Its wave is the one it is
    in now (brain.waves: the wave its props.carried_to names once the planned one closed without it, else the one it
    is part of), added to its parents when it is not part of it."""
    by = _part_of_milestones(nodes, edges, items)
    plan = waves.Plan(nodes)
    for nid, ms in by.items():
        plan.parents[nid] = sorted(ms)
    out = {}
    for nid in items:
        ms = by.get(nid, set())
        carried = ((nodes.get(nid) or {}).get("props") or {}).get("carried_to")
        if not ms and not carried:
            continue
        wave = plan.wave_of(nid) or ""
        thematic = sorted(m for m in ms if waves.kind(nodes[m]) != waves.WAVE)
        out[nid] = {"milestone": thematic[0] if thematic else "", "wave": wave,
                    "parents": sorted(ms | ({wave} if wave else set()))}
    return out


def gather(p: projects.Project, led: cost.Ledger, now: datetime) -> dict:
    """The model's inputs for project ``p``: its items with their estimates, the error ratios, the capacity, the
    scope's keep rate, the gates, the inflow and the deferred items; plain data (what the digest covers)."""
    store = resume.graph_store(p)
    if not store:
        raise ForecastError(f"{p.name}: no graph store")
    st = resume.Store.load(store)
    today = now.astimezone(timezone.utc).date()
    work = st.of_type("WorkItem")
    status = {n["id"]: str(n.get("status") or "") for n in work}
    deps: dict[str, list[str]] = {}
    for e in st.edges:
        if e.get("type") in ("depends_on", "gated_by") and e["from"] in status:
            deps.setdefault(e["from"], []).append(e["to"])
    parents = _parents(st.nodes, st.edges, status)
    pool = cost.history(led)
    ddrs = _ddrs(p.root)
    gates, delays = decision_gates(p.root, ddrs)
    acts, act_delays = action_gates(ddrs)
    ranker = ranking.Ranker(st.nodes, st.edges)   # the value brain next ranks by (features, milestone, unblocks)
    fl = flow(store, today)
    resolver = gate_data.Resolver(p.registry_dir or None, here=(p.name, st.nodes))

    def prepared(props: dict) -> list[dict]:
        return [gate_data.prepare(g, today=today, resolver=resolver, nodes=st.nodes, ddrs=ddrs, work=work, flow=fl)
                for g in gate_data.of(props)]

    def estimate(nid: str) -> dict:
        tgt = cost.target_of(led, nid) if nid in led.items else {"class": "standard", "theme": "", "milestone": "",
                                                                    "kind": "build", "chars": 0}
        e = cost.raw_estimate(pool, tgt)
        hours = {k: round(v / 3600, 4) for k, v in e["active_s"].items()} if e.get("active_s") else None
        usd = {k: round(v, 4) for k, v in e["cost"].items()} if e.get("cost") else None
        return {"class": tgt.get("class") or "standard", "basis": e["basis"], "n": e["n"], "hours": hours, "usd": usd}

    items, deferred = [], []
    for n in work:
        nid, s = n["id"], status[n["id"]]
        props = n.get("props") or {}
        if s not in resume.WORK_OPEN and s != DEFERRED:
            continue
        pri, proposed = _priority(props)
        est = estimate(nid)
        row = {"id": nid, "title": " ".join(str(n.get("title") or "").split())[:120], "status": s,
               "priority": pri, "proposed": proposed,
               **(parents.get(nid) or {"milestone": "", "wave": "", "parents": []}), **est}
        if s == DEFERRED:
            deferred.append(row)
            continue
        spent = 0.0
        if nid in led.items and s == "doing":
            spent = sum(sh * (r.get("active_s") or 0) for r, sh in led.items[nid].sessions) / 3600
        order = props.get("order")
        gs = prepared(props)
        after = [g["after"] for g in gs if g.get("after")]   # a calendar counted from an item's end: a dependency
        action = sorted(acts.get(nid, []))
        row.update(spent_h=round(spent, 4), order=order if isinstance(order, (int, float)) else None,
                   deps=sorted({d for d in deps.get(nid, []) + after if status.get(d) in resume.WORK_OPEN or
                                status.get(d) == DEFERRED}),
                   ddr=sorted(d for d in gates.get(nid, []) if d not in action), action=action, gates=gs,
                   due=str(props["due"])[:10] if _day(props.get("due")) else "",
                   why=_gate_text(s, props, resolver) or next((f"{g['undated']}" for g in gs if g.get("undated")), ""))
        effort = (est["hours"] or {}).get("median") or 1.0
        value = ranker.score(nid).value
        row["score"] = round(value / max(effort, 0.25), 4)
        items.append(row)
    milestones = []
    wplan = waves.build(st.nodes, st.edges)
    for m in st.of_type("Milestone"):
        if m.get("status") in ("reached", "dropped"):
            continue
        # a wave's members are the items in it now (carried in counted, carried out not: brain.waves), as the Tree's
        of = wplan.items_of(m["id"]) if waves.kind(m) == waves.WAVE else st.milestone_items(m["id"])
        members = [i for i in of if status.get(i) != "dropped"]
        trig = str((m.get("props") or {}).get("trigger") or "")
        gs = prepared(m.get("props") or {})
        milestones.append({"id": m["id"], "title": " ".join(str(m.get("title") or "").split())[:120],
                           "members": members, "done": sum(1 for i in members if status.get(i) == "done"),
                           "durations": [] if gs else sorted({w.group(0).lower() for w in _DURATION_RE.finditer(trig)}),
                           "gates": gs})
    reached = [{"id": m["id"], "reached": str((m.get("props") or {}).get("reached") or "")[:10]}
               for m in st.of_type("Milestone") if m.get("status") == "reached"]
    past = _past(led, status, {i for m in milestones for i in m["members"]})
    tests = cost.backtests(led, "active_s")
    ratios: dict[str, list[float]] = {"*": sorted(round(t["ratio"], 4) for t in tests if t["ratio"] > 0)}
    usd_tests = cost.backtests(led)
    usd_ratios: dict[str, list[float]] = {"*": sorted(round(t["ratio"], 4) for t in usd_tests if t["ratio"] > 0)}
    for src, dst in ((tests, ratios), (usd_tests, usd_ratios)):
        by: dict[str, list[float]] = {}
        for t in src:
            if t["ratio"] > 0:
                by.setdefault(t["class"] or "", []).append(round(t["ratio"], 4))
        dst.update({k: sorted(v) for k, v in by.items() if len(v) >= CLASS_MIN})
    starts = [d for d in (_day(fl.get("start")),) if d]
    starts += [_day(r.get("start")) for r in led.rows if r.get("served") and _day(r.get("start"))]
    cap = capacity(led.rows, min(starts) if starts else today, today)
    try:
        commit = _git(store, "rev-parse", "HEAD").strip()
    except (ForecastError, OSError, subprocess.TimeoutExpired):
        commit = ""
    model = {"project": p.name, "now": now.astimezone(timezone.utc).isoformat(timespec="minutes"),
             "items": items, "deferred": deferred, "milestones": milestones, "reached": reached,
             "ratios": ratios, "usd_ratios": usd_ratios, "history": len(pool), "capacity": cap,
             "keep": keep_rate(work), "delays_h": delays, "action_delays_h": act_delays, "flow": fl, "past": past}
    model["inputs"] = {"store_commit": commit, "store_digest": _store_digest(store), "model_digest": _digest(model),
                       "settings_digest": _digest(settings())}
    return model


def _past(led: cost.Ledger, status: dict[str, str], ids: set[str]) -> dict[str, dict]:
    """{item: {first, done, hours, sessions}}: what the ledger saw of each done or doing item of ``ids`` (the open
    milestones' members): the day of its first session, its done day (props.done, else its last session's), its
    active hours and its sessions; the item level's past bars read it (wi-brain-tui-trajectories-items)."""
    out = {}
    for nid in sorted(ids):
        it = led.items.get(nid)
        if status.get(nid) not in ("done", "doing") or not it or not it.sessions:
            continue
        out[nid] = {"first": it.first_start[:10], "done": it.done_day if status[nid] == "done" else "",
                    "hours": round(sum(sh * (r.get("active_s") or 0) for r, sh in it.sessions) / 3600, 2),
                    "sessions": len(it.sessions)}
    return out


def gate_kind(why: str) -> str:
    """'blocked', 'external blocker', 'after another project', 'after a deferred item', 'after an item not dated',
    'a dependency cycle' or 'no estimate': the part of a reason before its colon."""
    return why.split(":", 1)[0]


def _gate_text(status: str, props: dict, resolver: gate_data.Resolver | None = None) -> str:
    """Why an item cannot be dated ('' when it can): blocked, an external blocker, another project's item (none
    once ``after_external`` resolves to a ``<project>:<id>`` that is done)."""
    if status == "blocked":
        return "blocked" + (f": {str(props['external_blocker'])[:80]}" if props.get("external_blocker") else "")
    if props.get("external_blocker"):
        return f"external blocker: {str(props['external_blocker'])[:80]}"
    if props.get("after_external"):
        if resolver and resolver.status(props["after_external"]) == "done":
            return ""
        return f"after another project: {str(props['after_external'])[:80]}"
    return ""


# --- the futures ---

def _quantile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def quantiles(xs: list[float], extra: tuple = ()) -> dict:
    xs = sorted(xs)
    out = {k: round(_quantile(xs, q), 3) for k, q in (*extra, *QUANTILES)}
    return dict(sorted(out.items()))


class _Calendar:
    """One future's lane hours day after day, drawn by blocks of up to ``BLOCK_DAYS`` past days; ``w(t)``: a lane's
    work hours by day ``t`` (days from now), ``t(w)`` its inverse (the first moment it is reached)."""

    def __init__(self, rng: random.Random, hours: list[float], lanes: int) -> None:
        self.rng, self.hist, self.lanes = rng, hours, max(1, lanes)
        self.h: list[float] = []
        self.cum = [0.0]

    def _extend(self) -> None:
        n = len(self.hist)
        k = self.rng.randrange(n)
        for j in range(min(BLOCK_DAYS, n)):
            self.h.append(self.hist[(k + j) % n] / self.lanes)
            self.cum.append(self.cum[-1] + self.h[-1])

    def w(self, t: float) -> float:
        while len(self.h) <= t and len(self.h) < MAX_DAYS:
            self._extend()
        k = min(int(t), len(self.h) - 1)
        return self.cum[k] + (t - k) * self.h[k]

    def t(self, w: float) -> float:
        if w <= 0:
            return 0.0
        while self.cum[-1] < w and len(self.h) < MAX_DAYS:
            self._extend()
        if self.cum[-1] < w:
            return float(MAX_DAYS)
        k = bisect.bisect_left(self.cum, w) - 1  # cum[k] < w <= cum[k + 1]: day k has capacity
        return k + (w - self.cum[k]) / self.h[k]


def _plan(model: dict) -> dict:
    """The items the futures can date, in the scheduler's order, with the reason of each one that cannot."""
    by_id = {i["id"]: i for i in model["items"]}
    deferred = {i["id"] for i in model["deferred"]}
    why: dict[str, str] = {}
    state: dict[str, int] = {}

    def visit(nid: str) -> str:
        if state.get(nid) == 2:
            return why.get(nid, "")
        if state.get(nid) == 1:
            why[nid] = "a dependency cycle"
            return why[nid]
        state[nid] = 1
        it = by_id[nid]
        reason = it["why"] or ("no estimate: no finished item to estimate from" if not it["hours"] else "")
        for d in it["deps"]:
            if reason:
                break
            if d in deferred:
                reason = f"after a deferred item: {d}"
            elif d in by_id and visit(d):
                reason = f"after an item not dated: {d}"
        if reason:
            why[nid] = reason
        state[nid] = 2
        return reason

    for i in model["items"]:
        visit(i["id"])
    dated = [i for i in model["items"] if i["id"] not in why]
    held = {m["id"]: _held(m, set(why) | deferred) for m in model["milestones"]}

    def key(i: dict) -> tuple:
        return (0 if i["status"] == "doing" else 1, PRIORITY_RANK.get(i["priority"], 4), 1 if i["proposed"] else 0,
                i["order"] if i["order"] is not None else math.inf, -i["score"], i["id"])

    dated.sort(key=key)
    return {"dated": dated, "undated": {i: why[i] for i in sorted(why)},
            "milestones": {m: w for m, w in sorted(held.items()) if w}}


def _held(m: dict, undated: set[str]) -> str:
    """Why a milestone's own gates hold it undated ('' when they do not): a gate the forecast cannot date, or a
    calendar counted from an item not dated."""
    gs = m.get("gates") or []
    return (next((g["undated"] for g in gs if g.get("undated")), "")
            or next((f"after an item not dated: {g['after']}" for g in gs if g.get("after") in undated), ""))


def simulate(model: dict, runs: int = RUNS, seed: int = SEED) -> dict:
    """The futures: {item: [finish day or None (left out of that future)]}, and per future the hours and USD of the
    dated items it kept: plain lists, in the order of the futures."""
    plan = _plan(model)
    tasks = plan["dated"]
    idx = {t["id"]: k for k, t in enumerate(tasks)}
    deps = [[idx[d] for d in t["deps"] if d in idx] for t in tasks]
    dependents: list[list[int]] = [[] for _ in tasks]
    for k, ds in enumerate(deps):
        for d in ds:
            dependents[d].append(k)
    dur = [_lognormal(t["hours"]) for t in tasks]
    usd = [_lognormal(t["usd"]) for t in tasks]
    hist = [d["hours"] for d in model["capacity"]["days"]]
    lanes = [d["lanes"] for d in model["capacity"]["days"] if d["hours"] > 0] or [1]
    keep = model["keep"]["rate"]
    delays = model["delays_h"]
    act_delays = model.get("action_delays_h") or delays   # no action done yet: the owner's answer delays
    members = {m["id"]: set(m["members"]) for m in model["milestones"]}
    mgates = {m["id"]: m.get("gates") or [] for m in model["milestones"]
              if m.get("gates") and m["id"] not in plan["milestones"]}
    groups = {"*": list(range(len(tasks))), "": [k for k, t in enumerate(tasks) if not t["milestone"]],
              **{m: [k for k, t in enumerate(tasks) if t["id"] in ids] for m, ids in members.items()}}
    out = {"finish": {t["id"]: [] for t in tasks}, "start": {t["id"]: [] for t in tasks},
           "hours": {t["id"]: [] for t in tasks}, "runs": 0, "plan": plan,
           "work": {g: {"hours": [], "usd": []} for g in groups}, "mgate": {m: [] for m in mgates},
           "mgate_by": {m: [] for m in mgates},
           "groups": groups, "chains": {g: Counter() for g in groups}, "path_id": {}, "links": [],
           "gated": Counter(), "on_chain": {g: Counter() for g in groups}}
    if not tasks or not any(h > 0 for h in hist):
        return out
    for f in range(runs):
        rng = random.Random(f"{seed}:{f}")
        u = rng.random()
        factor = {c: _quantile(r, u) for c, r in model["ratios"].items()}
        usd_factor = {c: _quantile(r, u) for c, r in model["usd_ratios"].items()}
        cal = _Calendar(random.Random(f"{seed}:{f}:capacity"), hist, rng.choice(lanes))
        grng = random.Random(f"{seed}:{f}:gates")   # its own stream: a gate added leaves the other draws as they were
        d, kept, release, lag, dollars = [], [], [], [], []
        waits: dict[int, list[tuple[int, float]]] = {}   # an item -> the items whose calendar counts from its end
        for k, t in enumerate(tasks):
            z = rng.gauss(0.0, 1.0)  # one draw for the item's time and cost: they go together
            x = math.exp(dur[k][0] + dur[k][1] * z) * factor.get(t["class"], factor.get("*", 1.0))
            if t["status"] == "doing":
                x = max(x - t["spent_h"], REMAIN_MIN * x)
            d.append(x)
            kept.append(not t["proposed"] or rng.random() < keep)
            gate = rng.choice(delays) / 24 if t["ddr"] and delays else 0.0
            if t.get("action") and act_delays:
                gate = max(gate, grng.choice(act_delays) / 24)
            wait = 0.0
            for g in t.get("gates") or ():
                rel, lg = gate_data.draw(g, grng, delays)
                if g.get("after") in idx:   # counted from that item's own end, not from the last dependency's
                    waits.setdefault(idx[g["after"]], []).append((k, lg))
                    lg = 0.0
                gate, wait = max(gate, rel), max(wait, lg)
            release.append(cal.w(gate) if gate else 0.0)
            lag.append(wait)
            dollars.append(math.exp(usd[k][0] + usd[k][1] * z) * usd_factor.get(t["class"], usd_factor.get("*", 1.0))
                           if usd[k] else 0.0)
        trace: dict = {}
        done = _schedule(d, kept, release, deps, dependents, cal.lanes, lag, cal, waits, trace)
        for k, t in enumerate(tasks):
            out["finish"][t["id"]].append(round(cal.t(done[k]), 4) if kept[k] else None)
            out["start"][t["id"]].append(round(cal.t(trace["start"][k]), 4) if kept[k] else None)
            out["hours"][t["id"]].append(round(d[k], 4) if kept[k] else None)
        for m, gs in mgates.items():
            rels, lags = [(0.0, -1)], [0.0]   # (release, the item it counts from or -1)
            for g in gs:
                rel, lg = gate_data.draw(g, grng, delays)
                src = -1
                if g.get("after"):   # a calendar from an item's end: that item's finish in this future, plus the count
                    fin = (out["finish"].get(g["after"]) or [None])[-1] if g["after"] in idx else None
                    rel, lg = (fin or 0.0) + lg, 0.0
                    src = idx[g["after"]] if fin is not None else -1
                rels.append((rel, src))
                lags.append(lg)
            rel, src = max(rels, key=lambda r: (r[0], r[1] >= 0))   # a tie: the item's end sets it
            out["mgate"][m].append((rel, max(lags)))
            out["mgate_by"][m].append(src)
        _chains(out, groups, done, kept, trace, tasks)
        for g, ks in groups.items():
            out["work"][g]["hours"].append(sum(d[k] for k in ks if kept[k]))
            out["work"][g]["usd"].append(sum(dollars[k] for k in ks if kept[k]))
        out["runs"] += 1
    _tally(out, [t["id"] for t in tasks])
    del out["path_id"], out["links"], out["mgate_by"]
    return out


def _tally(out: dict, ids: list[str]) -> None:
    """The futures' chains by the items' ids, each counted by its items (whatever its links were in each future)
    with its links' most frequent labels; each item's count on its groups' chains (``on_chain``)."""
    for g, chains in out["chains"].items():
        on, total, labels = out["on_chain"][g], Counter(), {}
        for (pid, by), n in chains.items():
            total[pid] += n
            labels.setdefault(pid, Counter())[by] += n
        for pid, n in total.items():
            for k in out["links"][pid]:
                on[ids[k]] += n
        out["chains"][g] = Counter({(tuple(ids[k] for k in out["links"][pid]), labels[pid].most_common(1)[0][0]): n
                                    for pid, n in total.items()})


def _chains(out: dict, groups: dict[str, list[int]], done: list[float], kept: list[bool], trace: dict,
            tasks: list[dict]) -> None:
    """One future's critical chains: for each group, its last item to finish and, followed back through ``pred``,
    the items whose ends set it (members of the group or not: a lane another milestone's item held counts), counted
    per chain of task indices and what each link was in that future, in ``chains`` (``links``: a chain's items by its
    number; ``on_chain`` sums them per item once the futures are done, and the links' labels are the most frequent
    of the chain's). A milestone whose own gate is released after its items' end (and its lag) has its finish set by
    that gate: by the chain of the item a calendar counts from (``mgate_by``), else no chain in that future
    (``gated``)."""
    pred, by = trace["pred"], trace["by"]
    fin = [x if kept[k] else -1.0 for k, x in enumerate(done)]
    paths: dict[int, tuple[int, tuple[str, ...]]] = {}   # an end -> its chain: groups ending on one item share it
    seen: dict[int, tuple[tuple[int, ...], int]] = {}   # an item walked -> (a chain through it, its place there)
    for g, ks in groups.items():
        if not ks:
            continue
        end = max(ks, key=fin.__getitem__)    # ks ascend: a tie goes to the first in priority order
        if fin[end] < 0:
            continue
        end = _gated_end(out, g, end, fin, tasks)
        if end < 0:
            out["gated"][g] += 1
            continue
        key = paths.get(end)
        if key is None:   # once per end and future: a chain is hashed once, then counted by its number
            path = _walk(end, pred, seen, len(tasks))
            pid = out["path_id"].setdefault(path, len(out["path_id"]))
            if pid == len(out["links"]):
                out["links"].append(path)
            key = paths[end] = (pid, tuple(by[k] for k in path))
        out["chains"][g][key] += 1


def _gated_end(out: dict, g: str, end: int, fin: list[float], tasks: list[dict]) -> int:
    """The item whose chain set group ``g``'s finish in this future: its last item to end, unless its own gate is
    released later (and its lag): then the item that gate's calendar counts from (``mgate_by``), or -1 (no chain)."""
    gate = (out["mgate"].get(g) or [None])[-1]
    if gate is None or gate[0] <= out["finish"][tasks[end]["id"]][-1] + gate[1]:
        return end
    src = ((out.get("mgate_by") or {}).get(g) or [-1])[-1]
    return src if src >= 0 and fin[src] >= 0 else -1


def _walk(end: int, pred: list[int], seen: dict[int, tuple[tuple[int, ...], int]], n: int) -> tuple[int, ...]:
    """The chain to ``end``, first item first: ``pred`` followed back until an item a chain already walked in this
    future (``seen``, its head then shared) or one that waited on nothing; ``seen`` gains its new items."""
    walk, k = [], end
    while k >= 0 and k not in seen and len(walk) <= n:   # pred goes back in time: never a loop, bounded all the same
        walk.append(k)
        k = pred[k]
    head = seen[k][0][:seen[k][1] + 1] if k >= 0 and k in seen else ()
    path = head + tuple(reversed(walk))
    for i in range(len(head), len(path)):
        seen[path[i]] = (path, i)
    return path


def _schedule(dur: list[float], kept: list[bool], release: list[float], deps: list[list[int]],
              dependents: list[list[int]], lanes: int, lag: list[float] | None = None,
              cal: _Calendar | None = None, waits: dict[int, list[tuple[int, float]]] | None = None,
              trace: dict | None = None) -> list[float]:
    """The event queue: each item's finish in a lane's work hours. The items are given in priority order, so an
    item's index is its rank; an item left out is satisfied at once and holds no lane. ``lag``: calendar days an item
    still waits once all its dependencies are done (a Go/NoGo's answer); ``waits``: an item -> (a later item, calendar
    days it waits from that item's end: a calendar gate counted from it). Both turned into work hours by ``cal``.

    ``trace`` (a dict, filled): ``start`` each item's start in work hours, ``pred`` the item whose end let it start
    (-1: none) and ``by`` what that was (``BY``): ``now`` ready at once, ``gate`` released by a gate (``pred``: the
    item whose end it counts from, a Go/NoGo's lag after its last dependency or a calendar from an item; -1 for one
    absolute, a DDR's delay or a calendar day), ``dependency`` the last of its dependencies to end, ``lane`` the item
    whose end freed the lane it waited for (the capacity). Followed back from an item, ``pred`` is the chain that set
    its finish (wi-brain-forecast-starts-critical)."""
    waits = waits or {}
    n = len(dur)
    left = [sum(1 for d in deps[k] if kept[d]) for k in range(n)]
    done = [0.0] * n
    start = [0.0] * n
    pred = [-1] * n
    by = ["now"] * n
    since = [0.0] * n            # when an item joined the ready queue
    cause: list[tuple[str, int]] = [("now", -1)] * n
    src = [-1] * n               # the item whose end set an item's release (-1: an absolute gate, or none)
    freed = -1                   # the item whose end freed the last lane
    ready: list[int] = []
    waiting: list[tuple[float, int]] = []
    running: list[tuple[float, int]] = []

    def gate(k: int, at: float, after: int = -1) -> float:   # ``after``: the dependency that ended at ``at``
        if lag and cal and lag[k]:
            held = cal.w(cal.t(at) + lag[k])
            if after >= 0 and held >= release[k]:
                src[k] = after
            return max(release[k], held)
        return release[k]

    release = list(release)

    def ended(k: int, at: float) -> None:   # the calendars counted from k's end start at ``at``
        for j, days in waits.get(k, ()):
            held = cal.w(cal.t(at) + days) if cal else release[j]
            if held > release[j]:
                release[j], src[j] = held, k if kept[k] else -1   # an item left out ends at once: from now

    for k in range(n):
        if not kept[k]:
            ended(k, 0.0)
    for k in range(n):
        if kept[k] and not left[k]:
            release[k] = gate(k, 0.0)
            heapq.heappush(waiting, (release[k], k)) if release[k] > 0 else heapq.heappush(ready, k)
    now, free = 0.0, lanes
    while ready or waiting or running:
        while free and ready:
            k = heapq.heappop(ready)
            heapq.heappush(running, (now + dur[k], k))
            free -= 1
            start[k] = now
            # it waited in the queue: the lane's end let it start; else what made it ready
            by[k], pred[k] = ("lane", freed) if now > since[k] and freed >= 0 else cause[k]
        t_run = running[0][0] if running else math.inf
        t_rel = waiting[0][0] if waiting else math.inf
        if t_run == math.inf and t_rel == math.inf:
            break
        if t_run <= t_rel:
            now, k = heapq.heappop(running)
            done[k] = now
            free += 1
            freed = k
            ended(k, now)
            for j in dependents[k]:
                left[j] -= 1
                if kept[j] and not left[j]:
                    release[j] = gate(j, now, k)
                    if release[j] > now:
                        heapq.heappush(waiting, (release[j], j))
                    else:
                        since[j], cause[j] = now, ("dependency", k)
                        heapq.heappush(ready, j)
        else:
            now, k = heapq.heappop(waiting)
            since[k], cause[k] = now, ("gate", src[k])
            heapq.heappush(ready, k)
    if trace is not None:
        trace.update(start=start, pred=pred, by=by)
    return done


# --- the result ---

def calibration(reached: list[dict], snapshots: list[dict]) -> dict:
    """The judge on the snapshots (wi-brain-forecast-backtest replays the past): each reached milestone against the
    last snapshot taken before its date, covered when that date fell in the snapshot's p10-p90."""
    judged = covered = 0
    for m in reached:
        day = m.get("reached") or ""
        before = [s for s in snapshots if str(s.get("as_of") or "")[:10] < day and any(
            x["id"] == m["id"] and x.get("dates") for x in s.get("milestones") or [])]
        if not day or not before:
            continue
        snap = max(before, key=lambda s: s["as_of"])
        rng = next(x["dates"] for x in snap["milestones"] if x["id"] == m["id"])
        judged += 1
        covered += rng["p10"] <= day <= rng["p90"]
    cov = covered / judged if judged else None
    ok = judged >= CALIBRATED_MIN and abs(cov - COVERAGE) <= COVERAGE_TOL
    return {"state": "calibrated" if ok else "uncalibrated", "judged": judged, "covered": covered,
            "coverage": round(cov, 3) if cov is not None else None, "needed": CALIBRATED_MIN}


def _dates(now: datetime, q: dict) -> dict:
    return {k: (now + timedelta(days=v)).date().isoformat() for k, v in q.items()}


def _shown(q: dict | None) -> str:
    """'range' (p90 within the horizon), 'partial' (only p10 within it), 'beyond'; '' without futures."""
    if not q:
        return ""
    return "range" if q["p90"] <= HORIZON_DAYS else "partial" if q["p10"] <= HORIZON_DAYS else "beyond"


def _group(ids: list[str], sim: dict, gate: list[tuple[float, float]] | None = None) -> dict | None:
    """A milestone's or the backlog's finish: its latest dated item's in each future, as quantiles (days from now);
    a future that kept none of them finishes at once. ``gate``: the milestone's own gate in each future (released
    on a day, a lag after its items), which it waits on too."""
    finish = [sim["finish"][i] for i in ids if i in sim["finish"]]
    if not sim["runs"] or not (finish or gate):
        return None
    out = []
    for k in range(sim["runs"]):
        x = max((f[k] for f in finish if f[k] is not None), default=0.0)
        if gate:
            x = max(x + gate[k][1], gate[k][0])
        out.append(x)
    return quantiles(out)


def _work(sim: dict, g: str) -> dict | None:
    """The work left (d) in group ``g``: the hours and dollars of the items each future kept, p10-p90."""
    w = sim["work"].get(g)
    if not w or not w["hours"]:
        return None
    return {"hours": quantiles(w["hours"]), "usd": quantiles(w["usd"])}


def summarize(model: dict, sim: dict, runs: int, seed: int, snapshots: list[dict] | None = None) -> dict:
    now = datetime.fromisoformat(model["now"])
    plan = sim["plan"]
    n_runs = sim["runs"]
    by_id = {i["id"]: i for i in model["items"]}
    deferred_ids = {i["id"] for i in model["deferred"]}
    member_of: dict[str, list[str]] = {}
    for g, ks in (sim.get("groups") or {}).items():
        for k in ks:
            member_of.setdefault(plan["dated"][k]["id"], []).append(g)
    items = []
    for t in plan["dated"]:
        f = [x for x in sim["finish"][t["id"]] if x is not None]
        q = quantiles(f) if f else None
        dates = _dates(now, q) if q else None
        s = [x for x in (sim.get("start") or {}).get(t["id"]) or () if x is not None]
        qs = quantiles(s) if s else None
        h = [x for x in (sim.get("hours") or {}).get(t["id"]) or () if x is not None]
        items.append({"id": t["id"], "priority": t["priority"] + ("?" if t["proposed"] and t["priority"] else ""),
                      "milestone": t["milestone"], "wave": t.get("wave") or "",
                      "parents": list(t.get("parents") or ([t["milestone"]] if t["milestone"] else [])),
                      "status": t["status"], "basis": t["basis"],
                      "kept": round(len(f) / n_runs, 3) if n_runs else None, "days": q,
                      "dates": dates, "ddr": t["ddr"], "action": t.get("action") or [],
                      "gates": [g["label"] for g in t.get("gates") or [] if not g.get("passed")],
                      "due": t.get("due") or "", "late": bool(t.get("due") and dates and dates["p80"] > t["due"]),
                      "start": {"days": qs, "dates": _dates(now, qs)} if qs else None,
                      "hours": quantiles(h) if h else None,
                      "critical": {g: round(sim["on_chain"][g][t["id"]] / n_runs, 3) if n_runs else 0.0
                                   for g in sorted(member_of.get(t["id"], ()))} if "on_chain" in sim else {}})

    def block(ids: list[str], gate: list | None = None, held: str = "") -> dict:
        """The range of ``ids``; when one of them cannot be dated, none (the gate holds the whole group) and the
        range of the dated part apart."""
        q = _group(ids, sim, gate)
        out = {"days": q, "dates": _dates(now, q) if q else None, "shown": _shown(q)}
        if held or any(i in plan["undated"] for i in ids):
            return {"days": None, "dates": None, "shown": "undated", "part": out}
        return out

    milestones = []
    for m in model["milestones"]:
        open_ids = [i for i in m["members"] if i in by_id]
        held = plan.get("milestones", {}).get(m["id"], "")
        gate = (sim.get("mgate") or {}).get(m["id"])
        milestones.append({"id": m["id"], "title": m["title"], "items": len(m["members"]), "done": m["done"],
                           "open": len(open_ids), "dated": sum(1 for i in open_ids if i in sim["finish"]),
                           "undated": [i for i in open_ids if i in plan["undated"]],
                           "deferred": [i for i in m["members"] if i in deferred_ids], "durations": m["durations"],
                           "gates": [g["label"] for g in m.get("gates") or [] if not g.get("passed")],
                           "held": held, **block(open_ids, gate, held), "work": _work(sim, m["id"]),
                           "chain": _chain(sim, m["id"])})
    loose = [i["id"] for i in model["items"] if not i["milestone"]]
    no_ms = {"open": len(loose), "dated": sum(1 for i in loose if i in sim["finish"]), **block(loose),
             "work": _work(sim, ""), "chain": _chain(sim, "")}
    every = [i["id"] for i in model["items"]]
    back = {"open": len(every), "dated": len(plan["dated"]), "undated": len(plan["undated"]), **block(every),
            "work": _work(sim, "*"), "chain": _chain(sim, "*")}
    back["frozen"] = back.pop("part", None) or {k: back[k] for k in ("days", "dates", "shown")}
    if model["flow"].get("growing"):
        back.update(days=None, dates=None, shown="growing")
    gates = {"ddr": sorted({d for t in plan["dated"] for d in t["ddr"]}),
             "ddr_items": sorted(t["id"] for t in plan["dated"] if t["ddr"]),
             "delays_h": quantiles(model["delays_h"]) if model["delays_h"] else None,
             "undated": [{"id": i, "why": w, "milestone": by_id[i]["milestone"]} for i, w in plan["undated"].items()],
             "durations": [{"milestone": m["id"], "words": m["durations"]} for m in model["milestones"]
                           if m["durations"]],
             "action": sorted({d for t in plan["dated"] for d in t.get("action") or []}),
             "action_items": sorted(t["id"] for t in plan["dated"] if t.get("action")),
             "declared": _declared(model),
             "late": [{"id": i["id"], "due": i["due"], "p80": i["dates"]["p80"]} for i in items if i["late"]]}
    defer = model["deferred"]
    deferred = {"items": len(defer), "ids": [i["id"] for i in defer],
                "hours": round(sum((i["hours"] or {}).get("median") or 0 for i in defer)
                               * _median(model["ratios"].get("*")), 2),
                "usd": round(sum((i["usd"] or {}).get("median") or 0 for i in defer)
                             * _median(model["usd_ratios"].get("*")), 2)}
    caps = model["capacity"]["days"]
    work_days = [d for d in caps if d["hours"] > 0]
    return {"forecast": FORMAT, "project": model["project"], "as_of": model["now"], "seed": seed, "runs": n_runs,
            "code": {"brain": __version__, "model": MODEL_V}, "inputs": model["inputs"], "settings": settings(),
            "calibration": calibration(model["reached"], snapshots or []),
            "capacity": {"days": len(caps), "since": model["capacity"].get("since"), "work_days": len(work_days),
                         "hours": quantiles([d["hours"] for d in caps]) if caps else None,
                         "lanes": quantiles([d["lanes"] for d in work_days]) if work_days else None,
                         "total_h": round(sum(d["hours"] for d in caps), 2)},
            "error": {"backtests": len(model["ratios"].get("*") or []),
                      "ratio": quantiles(model["ratios"]["*"]) if model["ratios"].get("*") else None,
                      "classes": sorted(k for k in model["ratios"] if k != "*")},
            "scope": {"open": len(every), "dated": len(plan["dated"]),
                      "proposed": sum(1 for i in model["items"] if i["proposed"]), "keep": model["keep"],
                      "history": model["history"]},
            "flow": model["flow"], "gates": gates, "deferred": deferred, "quota": quota_pace(),
            "not_modelled": list(NOT_MODELLED), "backlog": back, "no_milestone": no_ms, "milestones": milestones,
            "items": items, "past": dict(sorted((model.get("past") or {}).items()))}


def _chain(sim: dict, g: str) -> dict | None:
    """Group ``g``'s most frequent critical chain: its items from the first to start to the last to end, what each
    one waited on (``by``: now, gate, dependency, lane), each one's criticality index for the group (``index``), the
    share of futures it was exactly that chain (``share``) and the share whose finish the group's own gate set
    (``gated``). None without futures or a chain."""
    runs, chains = sim.get("runs"), (sim.get("chains") or {}).get(g)
    gated = round((sim.get("gated") or {}).get(g, 0) / runs, 3) if runs else 0.0
    if not runs or not chains:
        return {"items": [], "by": [], "index": [], "share": 0.0, "gated": gated} if runs and gated else None
    (ids, by), n = max(chains.items(), key=lambda kv: (kv[1], kv[0]))
    on = sim["on_chain"][g]
    return {"items": list(ids), "by": list(by), "index": [round(on[i] / runs, 3) for i in ids],
            "share": round(n / runs, 3), "gated": gated}


def _declared(model: dict) -> list[dict]:
    """The gates written on the nodes (props.gate), each with what it holds: [{gate, kind, state, items,
    milestones}], state 'drawn', 'undated' or 'passed'."""
    out: dict[str, dict] = {}
    for kind, rows in (("items", model["items"]), ("milestones", model["milestones"])):
        for n in rows:
            for g in n.get("gates") or ():
                e = out.setdefault(g["label"], {"gate": g["label"], "kind": g["kind"], "state": (
                    "passed" if g.get("passed") else "undated" if g.get("undated") else "drawn"),
                    "items": [], "milestones": []})
                e[kind].append(n["id"])
    return [out[k] for k in sorted(out)]


def _median(xs: list[float] | None) -> float:
    return _quantile(xs, 0.5) if xs else 1.0


def run(model: dict, runs: int = RUNS, seed: int = SEED, snapshots: list[dict] | None = None) -> dict:
    return summarize(model, simulate(model, runs, seed), runs, seed, snapshots)


def forecast(p: projects.Project, led: cost.Ledger, now: datetime, runs: int = RUNS, seed: int = SEED) -> dict:
    """``p``'s forecast from the ledger ``led`` (brain.cost.load), judged on its saved snapshots."""
    return run(gather(p, led, now), runs, seed, load_snapshots(p.name))


# --- the quota (wi-brain-quota-pacing) ---

def quota_pace() -> str:
    """The quota line of brain.quota once it is there (wi-brain-quota-pacing), else 'quota pace unknown'."""
    try:
        q = importlib.import_module(".quota", __package__)
    except ModuleNotFoundError:
        return "quota pace unknown"
    try:
        line = (q.load_status() or {}).get("line") if hasattr(q, "load_status") else ""
    except (OSError, ValueError, AttributeError):
        line = ""
    return line or "quota pace unknown"


# --- the files ---

def folder(project: str) -> Path:
    return paths.brain_home() / "forecast" / project


def save(res: dict, snapshot: bool = False) -> Path:
    """latest.json (each run), or the week's snapshot ``<day>.json`` (brain cost audit --write)."""
    out = folder(res["project"]) / (f"{res['as_of'][:10]}.json" if snapshot else "latest.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(as_json(res) + "\n", encoding="utf-8")
    return out


def load_snapshots(project: str) -> list[dict]:
    out = []
    for f in sorted(folder(project).glob("????-??-??.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("as_of"):
            out.append(data)
    return out


def load_latest(project: str) -> dict:
    try:
        data = json.loads((folder(project) / "latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def as_json(res: dict) -> str:
    return json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True)


# --- text ---

def _md(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d:%b} {d.day}"


def span(block: dict, calibrated: bool = False) -> str:
    """'Nov 3 – Nov 7', 'Nov 20 – beyond 6 weeks', 'beyond 6 weeks'; p10 · p50 · p90 once calibrated."""
    shown, dt = block.get("shown"), block.get("dates")
    if not dt:
        return "no date"
    if shown == "beyond":
        return f"beyond {HORIZON_DAYS // 7} weeks"
    if shown == "partial":
        return f"{_md(dt['p10'])} – beyond {HORIZON_DAYS // 7} weeks"
    if calibrated:
        return f"{_md(dt['p10'])} · {_md(dt['p50'])} · {_md(dt['p90'])}"
    return f"{_md(dt['p10'])} – {_md(dt['p90'])}"


def _hours(w: dict | None) -> str:
    if not w or not w.get("hours"):
        return "-"
    h = w["hours"]
    return f"{h['p10']:.0f}–{h['p90']:.0f} h"


def _usd(q: dict | None) -> str:
    return f"${q['p10']:,.0f}–${q['p90']:,.0f}" if q else "-"


def label(res: dict) -> str:
    c = res["calibration"]
    return ("calibrated" if c["state"] == "calibrated" else
            f"uncalibrated: {c['judged']} of {c['needed']} reached milestones judged")


def growth(fl: dict) -> str:
    if not fl.get("days"):
        return "inflow unknown (no git history)"
    return (f"created {fl['created_per_day']:g}/day, closed {fl['closed_per_day']:g}/day over {fl['days']} day(s) "
            f"(s)")


def _kinds(ids: list[str], undated: list[dict]) -> str:
    """'2 after another project, 1 external blocker': the gates holding ``ids``, the most frequent first."""
    why = {u["id"]: u["why"] for u in undated}
    kinds = Counter(gate_kind(why[i]) for i in ids if i in why)
    return ", ".join(f"{n} {k}" for k, n in sorted(kinds.items(), key=lambda x: (-x[1], x[0])))


def backlog_line(res: dict) -> str:
    b, cal = res["backlog"], res["calibration"]["state"] == "calibrated"
    part = f" (its {b['dated']} dated items of {b['open']})" if b["undated"] else ""
    if b["shown"] == "growing":
        return (f"no date: it grows faster than it empties ({growth(res['flow'])}); today's scope alone{part}: "
                f"{span(b['frozen'], cal)} (d)")
    if b["shown"] == "undated":
        return (f"no date: {b['undated']} item(s) wait on gates the forecast cannot date; today's scope{part}: "
                f"{span(b['frozen'], cal)} (d)")
    if not b.get("dates"):
        return "no date: " + ("no observed capacity" if res["runs"] else "nothing to simulate")
    return f"{span(b, cal)} (d)" + ("; the inflow is not simulated" if res["flow"].get("days") else
                                    "; inflow unknown")


def _milestone_text(m: dict, undated: list[dict], cal: bool) -> str:
    if not m["open"] and not m.get("dates") and m["shown"] != "undated":
        text = f"no open item ({m['done']}/{m['items']} done): its trigger decides"
    elif m["shown"] == "undated":
        why = ", ".join(x for x in (gate_kind(m["held"]) if m.get("held") else "", _kinds(m["undated"], undated)) if x)
        text = f"not dated: {why}" + (
            f"; its dated part {span(m['part'], cal)}" if (m.get("part") or {}).get("dates") else "")
    else:
        text = span(m, cal)
    if m.get("deferred"):
        text += f"; {len(m['deferred'])} deferred item(s) out"
    if m.get("gates"):
        text += f"; gated: {', '.join(m['gates'])}"
    if m["durations"]:
        text += f"; its trigger names {', '.join(m['durations'])} with no gate (not modelled)"
    return text


def render(res: dict, show_items: bool = False) -> list[str]:
    cal = res["calibration"]["state"] == "calibrated"
    lines = [f"brain forecast {res['project']}: {res['as_of'].replace('T', ' ')[:16]} UTC, {res['runs']} futures, seed "
             f"{res['seed']} — {label(res).upper() if not cal else 'CALIBRATED'}",
             "  (s) measured, (d) derived, (e) estimated; dates p10–p90"
             + ("" if cal else ", the p50 alone once calibrated") + f"; beyond {HORIZON_DAYS // 7} weeks no date"]
    if not res["runs"]:
        why = ("no finished item with sessions to estimate from" if not res["scope"]["history"] else
               "no observed capacity in the last days" if not res["capacity"]["total_h"] else "no open item to date")
        lines.append(f"  nothing simulated: {why}")
    undated = res["gates"]["undated"]
    lines += ["", "Milestones (open items; work left p10–p90 (d); done p10–p90 (d))"]

    def order(m: dict) -> tuple:
        q = m.get("days") or (m.get("part") or {}).get("days")
        return (0 if m.get("days") else 1 if m["open"] else 2, (q or {}).get("p50", 0), m["id"])

    rows = sorted(res["milestones"], key=order)
    width = max([len(m["id"]) for m in rows] + [14])
    for m in rows:
        lines.append(f"  {m['id']:<{width}} {m['open']:>3} it.  {_hours(m.get('work')):>10}  "
                     f"{_milestone_text(m, undated, cal)}")
    nm = res["no_milestone"]
    if nm["open"]:
        text = (span(nm, cal) if nm.get("dates") else
                f"not dated: {_kinds([u['id'] for u in undated if not u['milestone']], undated)}"
                + (f"; its dated part {span(nm['part'], cal)}" if (nm.get("part") or {}).get("dates") else ""))
        lines.append(f"  {'(no milestone)':<{width}} {nm['open']:>3} it.  {_hours(nm.get('work')):>10}  {text}")
    b = res["backlog"]
    lines += ["", f"Whole backlog: {b['open']} open item(s), {b['dated']} dated; work left {_hours(b.get('work'))}, "
                  f"{_usd((b.get('work') or {}).get('usd'))} at API prices (d)",
              f"  {backlog_line(res)}"]
    c = res["capacity"]
    lines += ["", "Inputs"]
    if c["hours"]:
        lines.append(f"  capacity (s)   {c['work_days']} of {c['days']} day(s) since {c['since']} with item work, "
                     f"{c['total_h']:.0f} h; a day p10–p90 {c['hours']['p10']:.1f}–{c['hours']['p90']:.1f} h, "
                     f"median {c['hours']['p50']:.1f} h; lanes {c['lanes']['p10']:.0f}–{c['lanes']['p90']:.0f}"
                     if c["lanes"] else f"  capacity (s)   no item work in {c['days']} day(s)")
    e = res["error"]
    lines.append(f"  error F (s)    {e['backtests']} backtests of the active time, ratio actual/estimate p10 "
                 f"{e['ratio']['p10']:.2f} · p50 {e['ratio']['p50']:.2f} · p90 {e['ratio']['p90']:.2f}"
                 + (f"; own factor: {', '.join(e['classes'])}" if e["classes"] else "")
                 if e["ratio"] else "  error F        no backtest yet: F = 1 (the range is too narrow)")
    s = res["scope"]
    lines.append(f"  scope (s)      {s['proposed']} item(s) with a proposed priority, each kept with p "
                 f"{s['keep']['rate']:.2f} ({s['keep']['kept']} proposals kept, {s['keep']['dropped']} dropped)")
    g = res["gates"]
    if g["ddr"]:
        lines.append(f"  gates (s)      {len(g['ddr'])} blocking DDR(s) hold {len(g['ddr_items'])} item(s); "
                     f"{config.name_of()}'s "
                     f"answer p10–p90 {g['delays_h']['p10']:.1f}–{g['delays_h']['p90']:.1f} h" if g["delays_h"] else
                     f"  gates          {len(g['ddr'])} blocking DDR(s), no answered DDR to time them")
    if g["undated"]:
        lines.append(f"  not dated      {len(g['undated'])} item(s): {_kinds([u['id'] for u in undated], undated)} "
                     "(--items lists them)")
    if g.get("action"):
        lines.append(f"  actions (s)    {len(g['action'])} pending action(s) only {config.name_of()} may do hold "
                     f"{len(g['action_items'])} item(s), timed by the actions done")
    for x in g.get("declared") or ():
        held = ", ".join(f"{len(x[k])} {k[:-1]}(s)" for k in ("milestones", "items") if x[k])
        lines.append(f"  gate           {x['gate']} ({x['state']}) holds {held}")
    if g["durations"]:
        lines.append(f"  calendar       {len(g['durations'])} milestone trigger(s) name a duration with no gate, not "
                     "modelled: " + ", ".join(f"{x['milestone']} ({', '.join(x['words'])})" for x in g["durations"]))
    for x in g.get("late") or ():
        lines.append(f"  ALERT          {x['id']}: its p80 {x['p80']} passes its due date {x['due']}")
    d = res["deferred"]
    lines.append(f"  deferred       {d['items']} item(s) in the icebox, out of every date"
                 + (f"; if everything thawed: {d['hours']:.0f} h, ${d['usd']:,.0f} (e)" if d["items"] else ""))
    lines.append(f"  inflow         {growth(res['flow'])}; not simulated")
    lines.append(f"  quota          {res['quota']}")
    lines.append(f"  not modelled   {'; '.join(res['not_modelled'])}")
    lines.append(f"  inputs         store {res['inputs']['store_commit'][:10] or '-'} "
                 f"{res['inputs']['store_digest']}, model {res['inputs']['model_digest']}, brain "
                 f"{res['code']['brain']} model v{res['code']['model']}")
    if show_items:
        lines += ["", "Items (p10 · p50 · p80 · p90 (d); ? a proposed priority, kept: the share of futures)"]
        for it in sorted(res["items"], key=lambda i: ((i["days"] or {}).get("p50", 0), i["id"])):
            dt = it["dates"]
            when = " · ".join(_md(dt[k]) for k in ("p10", "p50", "p80", "p90")) if dt else "-"
            waits = [*it["ddr"], *(it.get("action") or []), *(it.get("gates") or [])]
            extra = (f" kept {it['kept']:.0%}" if it["kept"] is not None and it["kept"] < 1 else "") + (
                f" after {', '.join(waits)}" if waits else "") + (f" due {it['due']}" if it.get("due") else "")
            lines.append(f"  {it['id']:<42} {it['priority'] or '-':<4} {when}{extra}")
        for u in res["gates"]["undated"]:
            lines.append(f"  {u['id']:<42} not dated: {u['why']}")
    return lines


# --- the critical chains (wi-brain-forecast-starts-critical) ---

BACKLOG = "*"           # the whole backlog's group in the futures (its chain: backlog.chain)
CHAIN_SHOWN = 4         # a chain's items a line names before « … »


def _short_id(nid: str, project: str) -> str:
    pre = f"wi-{project}-"
    return nid[len(pre):] if project and nid.startswith(pre) else nid


def bound(chain: dict | None) -> str:
    """What a chain says of its group's finish: 'capacity-bound' (its links are mostly lanes another item freed),
    'dependency-bound' (mostly depends_on, or a gate counted from the item before: a Go/NoGo's lag, a calendar from
    an item), 'one item' (a chain of one), '' without one."""
    if not chain or not chain.get("items"):
        return ""
    links = chain["by"][1:]
    lane, dep = links.count("lane"), links.count("dependency") + links.count("gate")
    if not links:
        return "one item"
    return "capacity-bound" if lane >= dep else "dependency-bound"


def chain_text(chain: dict | None, project: str = "", res: dict | None = None, limit: int = CHAIN_SHOWN) -> str:
    """« a 41 % → b 38 % → … (+3) · capacity-bound: 2 lanes, 2.7 h/day · this chain in 12 % of futures »; its own
    gate when it set the finish in most futures; '' without a chain."""
    if not chain:
        return ""
    if not chain.get("items"):
        return f"its own gate sets its finish in {chain.get('gated', 0):.0%} of futures"
    names = [f"{_short_id(i, project)} {x:.0%}" for i, x in zip(chain["items"], chain["index"], strict=True)]
    head = " → ".join(names[:limit]) + (f" → … (+{len(names) - limit})" if len(names) > limit else "")
    kind = bound(chain)
    cap = (res or {}).get("capacity") or {}
    if kind == "capacity-bound" and cap.get("lanes") and cap.get("hours"):
        kind += f": {cap['lanes']['p50']:.0f} lane(s), {cap['hours']['p50']:.1f} h/day"
    tail = [kind] if kind else []
    if chain["by"] and chain["by"][0] == "gate":
        tail.append("after a gate")
    tail.append(f"this chain in {chain['share']:.0%} of futures")
    if chain.get("gated"):
        tail.append(f"its own gate sets the finish in {chain['gated']:.0%}")
    return " · ".join([head, *tail])


def group_of(res: dict, ref: str) -> tuple[str, dict] | None:
    """(group id, its block) for ``ref``: a milestone's id, the same without its ``ms-<project>-`` prefix, ``*`` or
    ``backlog`` (the whole backlog), ``-`` (no milestone); None when the forecast has no such group."""
    if ref in (BACKLOG, "backlog"):
        return BACKLOG, res.get("backlog") or {}
    if ref in ("-", "(no milestone)"):
        return "", res.get("no_milestone") or {}
    ms = {m["id"]: m for m in res.get("milestones") or []}
    for mid in (ref, f"ms-{res.get('project')}-{ref}", f"ms-{ref}"):
        if mid in ms:
            return mid, ms[mid]
    return None


def critical_lines(res: dict, ref: str | None = None) -> list[str]:
    """``brain forecast --critical``: each dated group's critical chain (the backlog first, then the milestones by
    their median); with ``ref`` one group's chain and its items, each with its criticality index, its start and its
    finish p10-p90, the items outside the group marked."""
    head = (f"brain forecast {res.get('project') or ''} --critical: "
            f"{str(res.get('as_of') or '').replace('T', ' ')[:16]} UTC, {res.get('runs', 0)} futures, "
            f"{label(res).upper()}")
    return [head, *(_every_chain(res) if ref is None else _one_chain(res, ref))]


def _every_chain(res: dict) -> list[str]:
    """Each group's chain, the backlog first, then the milestones by their median."""
    p = res.get("project") or ""
    out = ["  the chain of each group (most futures): criticality index, share of futures in which the item lies on "
           "the chain that sets the group's finish (Van Slyke 1963)"]
    rows = [("backlog", (res.get("backlog") or {}).get("chain"))]
    ms = sorted((m for m in res.get("milestones") or [] if m.get("chain")),
                key=lambda m: ((m.get("days") or (m.get("part") or {}).get("days") or {}).get("p50", math.inf),
                               m["id"]))
    rows += [(m["id"], m["chain"]) for m in ms]
    width = max([len(r[0]) for r in rows] + [14])
    out += [f"  {g:<{width}} {chain_text(c, p, res)}" for g, c in rows if c]
    return out if len(out) > 1 else [*out, "  no chain: nothing simulated"]


def _one_chain(res: dict, ref: str) -> list[str]:
    """One group's chain, its members by their index (◆ on the chain), then the items of other groups on it."""
    p = res.get("project") or ""
    found = group_of(res, ref)
    if found is None:
        raise ForecastError(f"--critical {ref}: no such milestone in the forecast (an id, its short name, backlog or -)")
    gid, block = found
    chain = block.get("chain")
    name = {BACKLOG: "backlog", "": "(no milestone)"}.get(gid, gid)
    out = [f"  {name}: {chain_text(chain, p, res) or 'no chain: nothing simulated'}"]
    by = {i["id"]: i for i in res.get("items") or []}
    members = [i for i in res.get("items") or [] if gid in (i.get("critical") or {})]
    on = set((chain or {}).get("items") or [])
    out.append("  ◆ on its chain · criticality index · start and end p10–p90 (d)")
    for i in sorted(members, key=lambda i: (-(i["critical"].get(gid) or 0), i["id"])):
        out.append(_critical_row(i, gid, i["id"] in on, p))
    return out + _outside(chain, gid, by, p)


def _outside(chain: dict | None, gid: str, by: dict[str, dict], project: str) -> list[str]:
    """The items of other groups on a group's chain (a lane they held, a dependency outside it), named in one line."""
    outside = [nid for nid in (chain or {}).get("items") or []
               if nid not in by or gid not in (by[nid].get("critical") or {})]
    if not outside:
        return []
    names = ", ".join(_short_id(x, project) for x in outside[:CHAIN_SHOWN]) + (
        ", …" if len(outside) > CHAIN_SHOWN else "")
    return [f"  and {len(outside)} item(s) of other groups on its chain: {names}"]


def _critical_row(it: dict, gid: str, on: bool, project: str) -> str:
    st, dt = (it.get("start") or {}).get("dates"), it.get("dates")
    when = (f"start {_md(st['p10'])}–{_md(st['p90'])}" if st else "start -") + (
        f", end {_md(dt['p10'])}–{_md(dt['p90'])}" if dt else "")
    crit = f"{(it.get('critical') or {}).get(gid, 0):.0%}"
    return f"  {'◆' if on else ' '} {_short_id(it['id'], project):<40} {it.get('priority') or '-':<4} {crit:>5}  {when}"


# --- brain queue: what a day of waiting costs (wi-brain-queue-priority) ---

def waiting(res: dict, ids, window: int = 7, today: date | None = None) -> dict:
    """What a day of the owner's waiting costs the milestones that ``ids`` (open items and milestones) move, from a
    forecast (``brain forecast --json``, its saved latest.json): for each dated item, its milestone's p50 minus its own
    p50 is its slack; waiting ``window`` days delays the milestone by what exceeds the slack, so its slip per day of
    waiting is ``max(0, window - slack) / window`` (1: on the critical path, 0: the slack absorbs the week). Returns
    the largest slip and its milestone, each item's slip, and the nearest held-up milestone with its p50 (days from
    ``today``). {} without a forecast."""
    if not res:
        return {}
    ms = {m["id"]: m for m in res.get("milestones") or [] if (m.get("days") or {}).get("p50") is not None}
    items = {i["id"]: i for i in res.get("items") or [] if (i.get("days") or {}).get("p50") is not None}
    late = 0
    if today is not None and res.get("as_of"):
        late = max(0, (today - date.fromisoformat(str(res["as_of"])[:10])).days)
    out: dict = {"slip": 0.0, "slip_milestone": "", "items": {}}
    moved = set()
    for nid in ids:
        if nid in ms:
            moved.add(nid)
        it = items.get(nid)
        # every milestone it is part of (its thematic one and its wave, wi-brain-forecast-two-parents): the slip is the
        # largest, the tightest milestone's; a forecast before the two parents names one
        own = [ms[x] for x in (it.get("parents") or [it.get("milestone")]) if x in ms] if it else []
        if not own:
            continue
        moved.update(x["id"] for x in own)
        m = min(own, key=lambda x: (x["days"]["p50"], x["id"]))
        slack = max(0.0, m["days"]["p50"] - it["days"]["p50"])
        slip = round(max(0.0, window - slack) / window, 3)
        out["items"][nid] = {"milestone": m["id"], "slack_days": round(slack, 1), "slip": slip,
                             "p50": (m.get("dates") or {}).get("p50", "")}
        if slip > out["slip"]:
            out["slip"], out["slip_milestone"] = slip, m["id"]
    if moved:
        near = min(moved, key=lambda mid: (ms[mid]["days"]["p50"], mid))
        out.update(nearest=near, nearest_days=round(max(0.0, ms[near]["days"]["p50"] - late), 1),
                   nearest_p50=(ms[near].get("dates") or {}).get("p50", ""))
    return out


# --- brain status ---

def status_line(res: dict) -> str:
    """The line brain status shows: the nearest milestone's range and the backlog's verdict."""
    if not res:
        return "no forecast yet (brain forecast)"
    cal = res["calibration"]["state"] == "calibrated"
    tag = "p10–p50–p90" if cal else "p10–p90, uncalibrated"
    near = [m for m in res["milestones"] if m.get("dates")]
    near.sort(key=lambda m: (m["days"]["p50"], m["id"]))
    head = f"next {near[0]['id']} {span(near[0], cal)} ({tag})" if near else "no milestone dated"
    b = res["backlog"]
    tail = (f"backlog no date: it grows faster than it empties ({res['flow']['created_per_day']:g}/day in, "
            f"{res['flow']['closed_per_day']:g}/day out)" if b["shown"] == "growing"
            else f"backlog {span(b, cal)}" if b.get("dates") else "backlog not dated")
    return f"{head}; {tail} (brain forecast)"


def status_of(p: projects.Project, root: Path | None, now: datetime, quick: bool = False) -> dict:
    """``p``'s forecast for brain status: computed with ``STATUS_RUNS`` futures and saved, or with ``--quick`` the
    last one saved, invalidated once the open items moved by more than ``INVALID_SCOPE``."""
    if quick:
        res = load_latest(p.name)
        if not res:
            return {"line": "no forecast saved (brain forecast)"}
        line = status_line(res) + f" as of {res['as_of'][:16].replace('T', ' ')} UTC"
        try:
            st = resume.Store.load(resume.graph_store(p))
            n = len(st.open_items())
        except (OSError, TypeError, ValueError):
            n = None
        was = (res.get("scope") or {}).get("open")
        if n is not None and was and abs(n - was) / was > INVALID_SCOPE:
            line += f"; invalidated: {was} open items then, {n} now"
        return {"line": line, "as_of": res["as_of"]}
    try:
        led = cost.load([p], root, refresh=False)
        res = forecast(p, led, now, runs=STATUS_RUNS)
    except (ForecastError, OSError, ValueError) as exc:
        return {"error": str(exc)}
    save(res)
    return {"line": status_line(res), "as_of": res["as_of"]}
