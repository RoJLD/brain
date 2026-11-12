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
  gates      an item a pending blocking DDR names starts once the owner answers, after a delay drawn from their past answers.
             An item blocked, with an external blocker, after another project's item or after a deferred one is not
             dated, nor is what waits on it: listed apart, with the milestone triggers that name a duration.

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

from . import __version__, config, cost, diffs, graph, paths, projects, ranking, records, resume

FORMAT = 1            # the JSON's layout
MODEL_V = 1           # the method's version: a snapshot says which one made it
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
                "(wi-brain-scope-rollups)", "calendar and hardware gates (wi-brain-forecast-gates)", "the inflow")
_DURATION_RE = re.compile(r"\b(?:\d+|one|two|three|four|five|six|seven|ten|thirty|sixty)\s+(?:days?|weeks?|months?)\b"
                          r"|\bin a row\b|\bconsecutive\b|\bcontinuous(?:ly)?\b", re.I)
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


def decision_gates(root: Path) -> tuple[dict[str, list[str]], list[float]]:
    """({item: [the pending blocking DDRs naming it]}, the hours the owner took to answer each answered DDR)."""
    gates: dict[str, list[str]] = {}
    delays = []
    for d in _ddrs(root):
        asked, answer = _ts((d.get("asked") or {}).get("at")), _ts((d.get("answer") or {}).get("at"))
        if asked and answer and answer >= asked:
            delays.append(round((answer - asked).total_seconds() / 3600, 3))
        if d.get("status") == "pending" and d.get("blocking"):
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
    part_of = {e["from"]: e["to"] for e in st.edges if e.get("type") == "part_of" and e["from"] in status
               and (st.nodes.get(e["to"]) or {}).get("type") == "Milestone"}
    pool = cost.history(led)
    gates, delays = decision_gates(p.root)
    ranker = ranking.Ranker(st.nodes, st.edges)   # the value brain next ranks by (features, milestone, unblocks)

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
               "priority": pri, "proposed": proposed, "milestone": part_of.get(nid, ""), **est}
        if s == DEFERRED:
            deferred.append(row)
            continue
        spent = 0.0
        if nid in led.items and s == "doing":
            spent = sum(sh * (r.get("active_s") or 0) for r, sh in led.items[nid].sessions) / 3600
        order = props.get("order")
        row.update(spent_h=round(spent, 4), order=order if isinstance(order, (int, float)) else None,
                   deps=sorted(d for d in deps.get(nid, []) if status.get(d) in resume.WORK_OPEN or
                               status.get(d) == DEFERRED),
                   ddr=sorted(gates.get(nid, [])),
                   why=_gate_text(s, props))
        effort = (est["hours"] or {}).get("median") or 1.0
        value = ranker.score(nid).value
        row["score"] = round(value / max(effort, 0.25), 4)
        items.append(row)
    milestones = []
    for m in st.of_type("Milestone"):
        if m.get("status") in ("reached", "dropped"):
            continue
        members = [i for i in st.milestone_items(m["id"]) if status.get(i) != "dropped"]
        trig = str((m.get("props") or {}).get("trigger") or "")
        milestones.append({"id": m["id"], "title": " ".join(str(m.get("title") or "").split())[:120],
                           "members": members, "done": sum(1 for i in members if status.get(i) == "done"),
                           "durations": sorted({w.group(0).lower() for w in _DURATION_RE.finditer(trig)})})
    reached = [{"id": m["id"], "reached": str((m.get("props") or {}).get("reached") or "")[:10]}
               for m in st.of_type("Milestone") if m.get("status") == "reached"]
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
    fl = flow(store, today)
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
             "keep": keep_rate(work), "delays_h": delays, "flow": fl}
    model["inputs"] = {"store_commit": commit, "store_digest": _store_digest(store), "model_digest": _digest(model),
                       "settings_digest": _digest(settings())}
    return model


def gate_kind(why: str) -> str:
    """'blocked', 'external blocker', 'after another project', 'after a deferred item', 'after an item not dated',
    'a dependency cycle' or 'no estimate': the part of a reason before its colon."""
    return why.split(":", 1)[0]


def _gate_text(status: str, props: dict) -> str:
    """Why an item cannot be dated ('' when it can): blocked, an external blocker, another project's item."""
    if status == "blocked":
        return "blocked" + (f": {str(props['external_blocker'])[:80]}" if props.get("external_blocker") else "")
    if props.get("external_blocker"):
        return f"external blocker: {str(props['external_blocker'])[:80]}"
    if props.get("after_external"):
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

    def key(i: dict) -> tuple:
        return (0 if i["status"] == "doing" else 1, PRIORITY_RANK.get(i["priority"], 4), 1 if i["proposed"] else 0,
                i["order"] if i["order"] is not None else math.inf, -i["score"], i["id"])

    dated.sort(key=key)
    return {"dated": dated, "undated": {i: why[i] for i in sorted(why)}}


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
    members = {m["id"]: set(m["members"]) for m in model["milestones"]}
    groups = {"*": list(range(len(tasks))), "": [k for k, t in enumerate(tasks) if not t["milestone"]],
              **{m: [k for k, t in enumerate(tasks) if t["id"] in ids] for m, ids in members.items()}}
    out = {"finish": {t["id"]: [] for t in tasks}, "runs": 0, "plan": plan,
           "work": {g: {"hours": [], "usd": []} for g in groups}}
    if not tasks or not any(h > 0 for h in hist):
        return out
    for f in range(runs):
        rng = random.Random(f"{seed}:{f}")
        u = rng.random()
        factor = {c: _quantile(r, u) for c, r in model["ratios"].items()}
        usd_factor = {c: _quantile(r, u) for c, r in model["usd_ratios"].items()}
        cal = _Calendar(random.Random(f"{seed}:{f}:capacity"), hist, rng.choice(lanes))
        d, kept, release, dollars = [], [], [], []
        for k, t in enumerate(tasks):
            z = rng.gauss(0.0, 1.0)  # one draw for the item's time and cost: they go together
            x = math.exp(dur[k][0] + dur[k][1] * z) * factor.get(t["class"], factor.get("*", 1.0))
            if t["status"] == "doing":
                x = max(x - t["spent_h"], REMAIN_MIN * x)
            d.append(x)
            kept.append(not t["proposed"] or rng.random() < keep)
            gate = rng.choice(delays) / 24 if t["ddr"] and delays else 0.0
            release.append(cal.w(gate) if gate else 0.0)
            dollars.append(math.exp(usd[k][0] + usd[k][1] * z) * usd_factor.get(t["class"], usd_factor.get("*", 1.0))
                           if usd[k] else 0.0)
        done = _schedule(d, kept, release, deps, dependents, cal.lanes)
        for k, t in enumerate(tasks):
            out["finish"][t["id"]].append(round(cal.t(done[k]), 4) if kept[k] else None)
        for g, ks in groups.items():
            out["work"][g]["hours"].append(sum(d[k] for k in ks if kept[k]))
            out["work"][g]["usd"].append(sum(dollars[k] for k in ks if kept[k]))
        out["runs"] += 1
    return out


def _schedule(dur: list[float], kept: list[bool], release: list[float], deps: list[list[int]],
              dependents: list[list[int]], lanes: int) -> list[float]:
    """The event queue: each item's finish in a lane's work hours. The items are given in priority order, so an
    item's index is its rank; an item left out is satisfied at once and holds no lane."""
    n = len(dur)
    left = [sum(1 for d in deps[k] if kept[d]) for k in range(n)]
    done = [0.0] * n
    ready: list[int] = []
    waiting: list[tuple[float, int]] = []
    running: list[tuple[float, int]] = []
    for k in range(n):
        if kept[k] and not left[k]:
            heapq.heappush(waiting, (release[k], k)) if release[k] > 0 else heapq.heappush(ready, k)
    now, free = 0.0, lanes
    while ready or waiting or running:
        while free and ready:
            k = heapq.heappop(ready)
            heapq.heappush(running, (now + dur[k], k))
            free -= 1
        t_run = running[0][0] if running else math.inf
        t_rel = waiting[0][0] if waiting else math.inf
        if t_run == math.inf and t_rel == math.inf:
            break
        if t_run <= t_rel:
            now, k = heapq.heappop(running)
            done[k] = now
            free += 1
            for j in dependents[k]:
                left[j] -= 1
                if kept[j] and not left[j]:
                    heapq.heappush(waiting, (release[j], j)) if release[j] > now else heapq.heappush(ready, j)
        else:
            now, k = heapq.heappop(waiting)
            heapq.heappush(ready, k)
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


def _group(ids: list[str], sim: dict) -> dict | None:
    """A milestone's or the backlog's finish: its latest dated item's in each future, as quantiles (days from now);
    a future that kept none of them finishes at once."""
    finish = [sim["finish"][i] for i in ids if i in sim["finish"]]
    if not finish or not sim["runs"]:
        return None
    return quantiles([max((f[k] for f in finish if f[k] is not None), default=0.0) for k in range(sim["runs"])])


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
    items = []
    for t in plan["dated"]:
        f = [x for x in sim["finish"][t["id"]] if x is not None]
        q = quantiles(f) if f else None
        items.append({"id": t["id"], "priority": t["priority"] + ("?" if t["proposed"] and t["priority"] else ""),
                      "milestone": t["milestone"], "status": t["status"], "basis": t["basis"],
                      "kept": round(len(f) / n_runs, 3) if n_runs else None, "days": q,
                      "dates": _dates(now, q) if q else None, "ddr": t["ddr"]})

    def block(ids: list[str]) -> dict:
        """The range of ``ids``; when one of them cannot be dated, none (the gate holds the whole group) and the
        range of the dated part apart."""
        q = _group(ids, sim)
        out = {"days": q, "dates": _dates(now, q) if q else None, "shown": _shown(q)}
        if any(i in plan["undated"] for i in ids):
            return {"days": None, "dates": None, "shown": "undated", "part": out}
        return out

    milestones = []
    for m in model["milestones"]:
        open_ids = [i for i in m["members"] if i in by_id]
        milestones.append({"id": m["id"], "title": m["title"], "items": len(m["members"]), "done": m["done"],
                           "open": len(open_ids), "dated": sum(1 for i in open_ids if i in sim["finish"]),
                           "undated": [i for i in open_ids if i in plan["undated"]],
                           "deferred": [i for i in m["members"] if i in deferred_ids], "durations": m["durations"],
                           **block(open_ids), "work": _work(sim, m["id"])})
    loose = [i["id"] for i in model["items"] if not i["milestone"]]
    no_ms = {"open": len(loose), "dated": sum(1 for i in loose if i in sim["finish"]), **block(loose),
             "work": _work(sim, "")}
    every = [i["id"] for i in model["items"]]
    back = {"open": len(every), "dated": len(plan["dated"]), "undated": len(plan["undated"]), **block(every),
            "work": _work(sim, "*")}
    back["frozen"] = back.pop("part", None) or {k: back[k] for k in ("days", "dates", "shown")}
    if model["flow"].get("growing"):
        back.update(days=None, dates=None, shown="growing")
    gates = {"ddr": sorted({d for t in plan["dated"] for d in t["ddr"]}),
             "ddr_items": sorted(t["id"] for t in plan["dated"] if t["ddr"]),
             "delays_h": quantiles(model["delays_h"]) if model["delays_h"] else None,
             "undated": [{"id": i, "why": w, "milestone": by_id[i]["milestone"]} for i, w in plan["undated"].items()],
             "durations": [{"milestone": m["id"], "words": m["durations"]} for m in model["milestones"]
                           if m["durations"]]}
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
            "items": items}


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
    if not m["open"]:
        text = f"no open item ({m['done']}/{m['items']} done): its trigger decides"
    elif m["shown"] == "undated":
        text = f"not dated: {_kinds(m['undated'], undated)}" + (
            f"; its dated part {span(m['part'], cal)}" if (m.get("part") or {}).get("dates") else "")
    else:
        text = span(m, cal)
    if m.get("deferred"):
        text += f"; {len(m['deferred'])} deferred item(s) out"
    if m["durations"]:
        text += f"; its trigger names {', '.join(m['durations'])} (not modelled)"
    return text


def render(res: dict, show_items: bool = False) -> list[str]:
    cal = res["calibration"]["state"] == "calibrated"
    lines = [f"brain forecast {res['project']}: {res['as_of'].replace('T', ' ')[:16]} UTC, {res['runs']} futures, seed "
             f"{res['seed']} — {label(res).upper() if not cal else 'CALIBRATED'}",
             f"  (s) measured, (d) derived, (e) estimated; dates p10–p90"
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
    if g["durations"]:
        lines.append(f"  calendar       {len(g['durations'])} milestone trigger(s) name a duration, not modelled: "
                     + ", ".join(f"{x['milestone']} ({', '.join(x['words'])})" for x in g["durations"]))
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
            extra = (f" kept {it['kept']:.0%}" if it["kept"] is not None and it["kept"] < 1 else "") + (
                f" after {', '.join(it['ddr'])}" if it["ddr"] else "")
            lines.append(f"  {it['id']:<42} {it['priority'] or '-':<4} {when}{extra}")
        for u in res["gates"]["undated"]:
            lines.append(f"  {u['id']:<42} not dated: {u['why']}")
    return lines


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
        m = ms.get(it.get("milestone")) if it else None
        if not m:
            continue
        moved.add(m["id"])
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
