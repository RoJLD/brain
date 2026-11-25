"""``brain wave propose``: the wave composer (wi-brain-wave-propose), at zero token. It drafts the next N waves from the
graph: which open items go in which wave, cut into lots and rounds, against a capacity, with what each wave waits on
from the owner, the items left out and why, and the questions that need judgement. It prints a proposal, writes
nothing and refuses nothing; the coordinator composes the waves from it (``brain wave add``, ``brain item link
part_of``, ``brain wave plan``).

**Inputs.** The store's open items (brain.waves), with the items merged but not closed counted done
(brain.closemerged's mapping through :func:`brain.lots.merged_of`, git only); their ``depends_on`` edges; their
placements (brain.placement: ``props.place``, else the free text's placement words); their rank (brain.ranking: the
owner's priority, the owner's order, value over effort); their size in points (:data:`POINTS`); the lot cutter of
``brain wave plan`` (brain.lots: weighted surfaces, hot files, lot and chain caps).

**The windows.** The N waves after ``--from`` (default: the last pending wave, the one composed last), by their
place: ``s(N+1)``... Each window holds at most the capacity: ``--items`` and ``--points``, else what the last reached
waves closed (:func:`capacity`: the median of their done items and points, :data:`HISTORY_WAVES` of them), else
:data:`DEFAULT_ITEMS` and :data:`DEFAULT_POINTS`. About :data:`brain.waves.QUICKWIN_SHARE` of the places are kept for
quick wins (size S, high value).

**Out.** Before any fill: a blocked item, one with an external blocker, one whose placement is out (owner, later, a
trigger), one placed after an era's exit (« after 1.0 ») with no wave named, one pinned beyond the drafted waves, one
in a ``depends_on`` cycle. Each is listed with its reason.

**The fill**, wave by wave: the items pinned to it first (over the capacity if need be: a question), then those due
in it (their latest wave), then by rank, an item due before an era's exit (« before 1.0 ») first; an item goes in when
its placement allows that wave (earliest, latest, pin), every open prerequisite is placed in an earlier wave or in the
same one within a chain of :data:`brain.lots.CHAIN_CAP`, and the capacity holds; an item it must go ``with`` follows
it when it can. A standing item (``props.standing``, or a debt item, ``props.audit_repo``) is a batch in every wave.

**The lots.** Each wave's items are cut by :func:`brain.lots.cut`, an ``own-lot`` item taken out to a lot of its own,
and put in rounds by :func:`brain.lots.rounds_of` with the caps in force.

**The checks.** No item before a prerequisite, none twice, every pin within the window honoured, the capacity: what
fails is listed (``checks``), never hidden. ``--against FILE`` (an earlier ``--json``) says what moved.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import collisions, lots, placement, resume, waves

FORMAT = 1
POINTS = {"S": 1, "M": 2, "L": 4, "XL": 8}   # a size's points (the roadmap's lots: an L is four S)
DEFAULT_SIZE = "M"
DEFAULT_ITEMS = 12     # a window's items when no reached wave tells
DEFAULT_POINTS = 32    # a window's points when no reached wave tells
HISTORY_WAVES = 3      # the last reached waves the capacity is read from
OUT_SHOWN = 20         # the out list's length (``--all``: every one)
MAX_LOTS = 6           # a wave's lots at most (sessions; spec Part 2, step 8): lots that share no file join


@dataclass
class Wave:
    seq: int
    id: str
    release: str
    kind: str                                      # patch or minor (a one-way door placed)
    items: list[dict] = field(default_factory=list)
    standing: list[str] = field(default_factory=list)
    lots: list[dict] = field(default_factory=list)
    rounds: list[list[int]] = field(default_factory=list)
    doors: list[str] = field(default_factory=list)
    size: dict = field(default_factory=dict)
    waits: list[str] = field(default_factory=list)
    exit: list[str] = field(default_factory=list)


@dataclass
class Proposal:
    start: str
    capacity: dict
    waves: list[Wave]
    out: list[dict]
    questions: list[str]
    checks: list[str]
    merged: list[str]
    eras: list[dict]
    risks: list[str]
    diff: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"format": FORMAT, "from": self.start, "capacity": self.capacity,
                "waves": [asdict(w) for w in self.waves], "out": self.out, "questions": self.questions,
                "checks": self.checks, "merged": self.merged, "eras": self.eras, "risks": self.risks,
                "diff": self.diff}


def points(plan: waves.Plan, nid: str) -> int:
    size = str(waves._props(plan.nodes.get(nid) or {}).get("size") or "").upper()
    return POINTS.get(size, POINTS[DEFAULT_SIZE])


def capacity(plan: waves.Plan, items: int | None = None, pts: int | None = None) -> dict:
    """A window's capacity: ``items`` and ``pts`` when given, else the median of what the last reached waves closed
    (their done items and their points), else the defaults; ``basis`` says which."""
    seen_items, seen_pts, n = _seen(plan)
    basis = "given" if items is not None or pts is not None else (
        f"the median of the last {n} reached wave(s)" if n else "the defaults (no reached wave)")
    n_items = items or seen_items or DEFAULT_ITEMS
    return {"items": n_items, "points": pts or seen_pts or DEFAULT_POINTS, "basis": basis,
            "quick_wins": max(1, round(n_items * waves.QUICKWIN_SHARE))}


def _seen(plan: waves.Plan) -> tuple[int | None, int | None, int]:
    """(items, points, waves read): the medians of the done items of the last reached waves that closed any."""
    reached = [w for w in plan.waves if plan.status(w) == "reached"][-HISTORY_WAVES:]
    done = [d for d in ([i for i in plan.items_of(w) if plan.status(i) == "done"] for w in reached) if d]
    if not done:
        return None, None, 0
    return (int(statistics.median(len(d) for d in done)),
            int(statistics.median(sum(points(plan, i) for i in d) for d in done)), len(done))


def _standing(plan: waves.Plan, nid: str) -> bool:
    p = waves._props(plan.nodes.get(nid) or {})
    return bool(p.get("audit_repo")) or str(p.get("standing") or "").lower() in ("true", "yes", "1")


def _door(plan: waves.Plan, nid: str) -> bool:
    p = waves._props(plan.nodes.get(nid) or {})
    marks = " ".join(str(p.get(k) or "") for k in ("size_reason", "door", "one_way_door")).lower()
    return bool(p.get("door") or p.get("one_way_door")) or "one-way door" in marks


def _cycles(plan: waves.Plan, ids: set[str]) -> set[str]:
    """The open items in a depends_on cycle among ``ids``."""
    found: set[str] = set()
    state: dict[str, int] = {}

    def visit(i: str, path: list[str]) -> None:
        state[i] = 1
        for d in plan.blockers(i):
            if d not in ids:
                continue
            if state.get(d) == 1:
                found.update(path[path.index(d):] if d in path else [d, i])
            elif d not in state:
                visit(d, path + [d])
        state[i] = 2

    for i in sorted(ids):
        if i not in state:
            visit(i, [i])
    return found


class _Fill:
    """The fill of the windows: where each item goes, what is left out and why, the questions."""

    def __init__(self, plan: waves.Plan, pls: dict[str, placement.Placement], windows: list[int], cap: dict):
        self.plan, self.pls, self.windows, self.cap = plan, pls, windows, cap
        self.at: dict[str, int] = {p.item: p.pin for p in pls.values() if p.status == "composed" and p.pin}
        self.out: dict[str, str] = {}
        self.questions: list[str] = []
        self.placed: dict[int, list[str]] = {k: [] for k in windows}
        self.room: dict[str, str] = {}   # item -> why it waited (capacity, dependency, window)
        self.pending: list[str] = []

    # -- before the fill --
    def exclude(self, cands: list[str]) -> list[str]:
        cyc = _cycles(self.plan, set(cands))
        keep = []
        for i in cands:
            why = self._why_out(i, cyc)
            if why:
                self.out[i] = why
            else:
                keep.append(i)
        if cyc:
            self.questions.append(f"a depends_on cycle: {', '.join(sorted(cyc))} (left out until it is broken)")
        return keep

    def _why_out(self, i: str, cyc: set[str]) -> str:
        ext = waves._props(self.plan.nodes.get(i) or {}).get("external_blocker")
        if self.plan.status(i) == "blocked":
            return "blocked"
        if ext:
            return f"external: {waves._short(ext, 60)}"
        p = self.pls.get(i)
        return (self._placed_out(p) if p else "") or ("a depends_on cycle" if i in cyc else "")

    def _placed_out(self, p: placement.Placement) -> str:
        """Out by its placement: out (owner, later, a trigger), after an era's exit with no wave, pinned beyond."""
        if p.out:
            return p.out + (f": {p.why}" if p.why else "")
        if p.after_stage and p.pin is None and not p.choice:
            return f"after {p.after_stage} (no wave named)"
        if p.pin and p.pin > self.windows[-1]:
            return f"pinned to s{p.pin}, beyond the drafted waves"
        return ""

    # -- the fill --
    def bounds(self, i: str) -> tuple[int, int]:
        p = self.pls.get(i)
        lo, hi = self.windows[0], 10 ** 6
        if p and p.choice:
            lo = max(lo, min(p.choice))
        if p and p.pin is not None and p.pin >= self.windows[0]:
            lo, hi = p.pin, p.pin   # an overdue pin (a wave composed without it) bounds nothing: it comes first
        if p and p.earliest is not None:
            lo = max(lo, p.earliest)
        if p and p.latest is not None and p.pin is None:
            hi = max(self.windows[0], p.latest)
        return lo, hi

    def deps_ok(self, i: str, k: int) -> bool:
        """Every open prerequisite of ``i`` placed before wave ``k``, or in it within the chain cap."""
        for d in self.plan.blockers(i):
            w = self.at.get(d)
            if w is None or w > k:
                self.room[i] = f"dependency: {d} not placed before s{k}"
                return False
            if w == k and self._chain(d, k) >= lots.CHAIN_CAP:
                self.room[i] = f"dependency: {d}'s chain in s{k} is at the cap ({lots.CHAIN_CAP})"
                return False
        return True

    def _chain(self, i: str, k: int) -> int:
        """The longest chain of items in wave ``k`` that ends at ``i``."""
        here = [d for d in self.plan.blockers(i) if self.at.get(d) == k]
        return 1 + max((self._chain(d, k) for d in here), default=0)

    def fits(self, k: int, i: str, force: bool = False) -> bool:
        used = self.placed[k]
        n, pts = len(used), sum(points(self.plan, x) for x in used)
        if force or (n < self.cap["items"] and pts + points(self.plan, i) <= self.cap["points"]):
            return True
        self.room[i] = "capacity"
        return False

    def put(self, i: str, k: int) -> None:
        self.at[i] = k
        self.placed[k].append(i)
        self.room.pop(i, None)
        for t in (self.pls[i].together if i in self.pls else ()):
            if t in self.at:
                continue
            if t in self.pending and self._eligible(t, k) and self.fits(k, t):
                self.put(t, k)
            else:
                self.questions.append(f"{i} goes with {t}, which could not follow it into s{k}")

    def _eligible(self, i: str, k: int) -> bool:
        lo, hi = self.bounds(i)
        if not lo <= k <= hi:
            self.room.setdefault(i, f"window: from s{lo}" if k < lo else f"window: due by s{hi}")
            return False
        return self.deps_ok(i, k)

    def run(self, cands: list[str]) -> None:
        self.pending = list(cands)
        rank = self.plan.ranker.key
        late = self._late(cands)
        due = {i for i in cands if (p := self.pls.get(i)) and (p.before or p.latest is not None)}
        order = sorted(cands, key=lambda i: (i not in late, i not in due, rank(i)))
        for k in self.windows:
            self._pins(k)
            for reserve in (True, False):   # the quick-win places, kept, then given to the rest if none came
                while self._pass(k, order, reserve):   # a placed item may let its dependents in, in the same wave
                    pass
            self.pending = [i for i in self.pending if i not in self.at]

    def _late(self, cands: list[str]) -> set[str]:
        """The items that come first, each a question: pinned to a wave composed without them, or waited on by a
        composed item."""
        first = self.windows[0]
        late = {i for i in cands if (p := self.pls.get(i)) and p.pin is not None and p.pin < first}
        self.questions += [f"{i} is pinned to s{self.pls[i].pin}, which was composed without it: drafted from "
                           f"s{first}, first" for i in sorted(late)]
        held = self._held(set(cands))
        self.questions += [f"{c} (composed in s{self.at[c]}) waits on {d}, in no wave: drafted from s{first}, first"
                           for d, c in sorted(held.items())]
        return late | set(held)

    def _held(self, cands: set[str]) -> dict[str, str]:
        """The candidates a composed item waits on (prerequisite -> the first composed item that waits): due first."""
        out: dict[str, str] = {}
        for c in sorted(self.at):
            for d in self.plan.blockers(c):
                if d in cands:
                    out.setdefault(d, c)
        return out

    def _pins(self, k: int) -> None:
        for i in [i for i in self.pending if (p := self.pls.get(i)) and p.pin == k]:
            if i in self.at:
                continue
            if not self.deps_ok(i, k):
                self.questions.append(f"{i} is pinned to s{k}, but {self.room[i].removeprefix('dependency: ')}")
            over = not self.fits(k, i)
            self.put(i, k)
            if over:
                self.questions.append(f"{i} is pinned to s{k}, over its capacity")

    def _pass(self, k: int, order: list[str], keep_quick: bool = True) -> bool:
        changed = False
        quick = sum(1 for i in self.placed[k] if self.plan.ranker.score(i).quick_win)
        for i in order:
            if i in self.at or i not in self.pending or not self._eligible(i, k):
                continue
            qw = self.plan.ranker.score(i).quick_win
            reserve = 0 if qw or not keep_quick else max(0, self.cap["quick_wins"] - quick)
            if len(self.placed[k]) + reserve >= self.cap["items"] or not self.fits(k, i):
                self.room[i] = "capacity"
                continue
            self.put(i, k)
            quick += qw
            changed = True
        return changed


def _start(plan: waves.Plan, start: str) -> str:
    if start:
        w = plan.resolve(start) or plan.resolve(start.removeprefix("wave-"))
        if not w:
            raise ValueError(f"--from {start}: no wave of that release or id")
        return w
    pend = [w for w in plan.waves if plan.status(w) == "pending"]
    if pend:
        return pend[-1]
    if not plan.waves:
        raise ValueError("no wave in the store (brain wave add)")
    return plan.waves[-1]


def _next_release(label: str, minor: bool) -> str:
    key = waves.release_key(label)
    if key is None:
        return ""
    major, mi, patch = key
    return f"{major}.{mi + 1}.0" if minor else f"{major}.{mi}.{patch + 1}"


def _row(plan: waves.Plan, nid: str, k: int, why: str = "") -> dict:
    p = waves._props(plan.nodes.get(nid) or {})
    return {"id": nid, "priority": str(p.get("priority") or ""), "size": str(p.get("size") or ""),
            "points": points(plan, nid), "title": waves._short(str((plan.nodes.get(nid) or {}).get("title") or ""),
                                                                 80), "why": why}


def _lots(plan: waves.Plan, st: resume.Store, ids: list[str], own: set[str], at_once: int) -> tuple[list, list]:
    """A wave's lots and rounds: the lot cutter's, an own-lot item taken out to a lot of its own."""
    if not ids:
        return [], []
    code = collisions.coderefs(st)
    units = {i: lots._unit(plan, st, i, (), (), code) for i in ids}
    for i, u in units.items():
        u.after = sorted(lots._inside(plan, i, set(units)))
    found = _grouped(plan, _alone(lots.cut(units).lots, units, own), units, own)
    return _numbered(lots.rounds_of(found, units, at_once))


def _alone(cut: list, units: dict, own: set[str]) -> list:
    """The cutter's lots, each own-lot item taken out to a lot of its own."""
    found = []
    for lot in cut:
        alone = [i for i in lot.items if i in own and len(lot.items) > 1]
        found += [lots.Lot(0, [i], units[i].files, units[i].hot, lot.unblocks, units[i].known) for i in alone]
        lot.items = [i for i in lot.items if i not in alone]
        found += [lot] if lot.items else []
    return found


def _numbered(rounds: list[list]) -> tuple[list, list]:
    """The lots numbered in round order, as dicts, and the rounds as lists of lot numbers."""
    numbered = [lot for g in rounds for lot in g]
    for n, lot in enumerate(numbered, 1):
        lot.n = n
    for r, g in enumerate(rounds, 1):
        for lot in g:
            lot.round = r
    return [asdict(lot) for lot in numbered], [[lot.n for lot in g] for g in rounds]


def _grouped(plan: waves.Plan, found: list, units: dict, own: set[str]) -> list:
    """The cutter's lots gathered into :data:`MAX_LOTS` sessions at most: lots that share no file may run in one
    session in turn, so lots of one module join first, then the smallest pairs, never over :data:`brain.lots.LOT_CAP`
    items, never a broad lot or an own-lot one."""
    fixed = [lot for lot in found if lot.broad or set(lot.items) & own]
    free = [lot for lot in found if lot not in fixed]

    def module(lot) -> str:
        return str(waves._props(plan.nodes.get(lot.items[0]) or {}).get("module") or "")

    groups: dict[str, list] = {}
    for lot in free:
        groups.setdefault(module(lot) or lot.items[0], []).append(lot)
    merged = [m for g in groups.values() for m in _pack(g)]
    merged.sort(key=lambda lot: len(lot.items))
    while len(merged) + len(fixed) > MAX_LOTS and len(merged) > 1 \
            and len(merged[0].items) + len(merged[1].items) <= lots.LOT_CAP:
        merged = sorted([_join([merged[0], merged[1]])] + merged[2:], key=lambda lot: len(lot.items))
    out = merged + fixed
    for lot in out:
        lot.items = lots._order(lot.items, units)
    return out


def _pack(group: list) -> list:
    """One module's lots, joined in turn while they stay within the lot cap."""
    out: list = []
    for lot in sorted(group, key=lambda x: -len(x.items)):
        fit = next((o for o in out if len(o.items) + len(lot.items) <= lots.LOT_CAP), None)
        if fit is None:
            out.append(lot)
        else:
            out[out.index(fit)] = _join([fit, lot])
    return out


def _join(group: list):
    return lots.Lot(0, [i for lot in group for i in lot.items], sorted({f for lot in group for f in lot.files}),
                    sorted({f for lot in group for f in lot.hot}), sum(lot.unblocks for lot in group),
                    all(lot.checked for lot in group))


def propose(store: Path, root: Path | None = None, n: int = 3, start: str = "", repos=None,
            items: int | None = None, pts: int | None = None, at_once: int | None = None, project: str = "",
            read_merged: bool = True) -> Proposal:
    """The draft of the ``n`` waves after ``start`` (see the module's docstring)."""
    plan = waves.load(store, root)
    wid = _start(plan, start)
    merged: list[str] = []
    if repos and read_merged:
        merged = sorted(i for i in lots.merged_of(plan, wid, repos)[1] if not _standing(plan, i))   # a batch merged
        # leaves a standing item standing
        plan = lots.as_done(plan, merged)
    pls = placement.placements(plan)
    base = placement._Ctx.of(plan).pos.get(wid, len(plan.waves))
    windows = list(range(base + 1, base + 1 + max(1, n)))
    cap = capacity(plan, items, pts)
    fill = _Fill(plan, pls, windows, cap)
    open_ = [i for i in sorted(plan.nodes) if plan.is_item(i) and plan.status(i) in waves.OPEN]
    standing = [i for i in open_ if _standing(plan, i)]
    cands = [i for i in open_ if pls[i].status != "composed" and i not in standing]
    fill.run(fill.exclude(cands))
    caps = lots.caps_in_force(root, project, at_once)
    st = resume.Store.load(store)
    drafted = _waves(plan, st, pls, fill, wid, standing, caps["at_once"], cap)
    out = _out(plan, fill)
    questions = _questions(pls, fill)
    return Proposal(plan.label(wid) or wid, cap, drafted, out, questions, _checks(plan, fill, pls), merged,
                    _eras(plan, pls, fill), _risks(drafted, cap))


def _waves(plan, st, pls, fill: _Fill, wid: str, standing: list[str], at_once: int, cap: dict) -> list[Wave]:
    out = []
    label = plan.label(wid)
    for k in fill.windows:
        ids = fill.placed[k]
        doors = [i for i in ids if _door(plan, i)]
        label = _next_release(label, bool(doors)) or label
        lot_rows, rounds = _lots(plan, st, ids, {i for i in ids if pls[i].own_lot}, at_once)
        pts = sum(points(plan, i) for i in ids)
        w = Wave(k, f"wave-s{k}", label, "minor" if doors else "patch",
                 [_row(plan, i, k) for i in ids], list(standing), lot_rows, rounds, doors,
                 {"items": len(ids), "points": pts, "of_items": cap["items"], "of_points": cap["points"]})
        w.waits = sorted({f"{i}: {x}" for i in ids for x in plan.owner_waits(i)})
        w.exit = [f"{len(ids)} item(s) merged", f"tag v{label}" if label else "the tag"]
        out.append(w)
    return out


def _out(plan: waves.Plan, fill: _Fill) -> list[dict]:
    rows = [{"id": i, "why": why, "rank": list(map(str, plan.ranker.key(i)))} for i, why in fill.out.items()]
    rows += [{"id": i, "why": fill.room.get(i, "capacity"), "rank": list(map(str, plan.ranker.key(i)))}
             for i in fill.pending if i not in fill.at]
    return sorted(rows, key=lambda r: plan.ranker.key(r["id"]))


def _questions(pls: dict[str, placement.Placement], fill: _Fill) -> list[str]:
    asked = [q for i in sorted(set(fill.at) | set(fill.pending)) if i in pls for q in pls[i].questions()]
    return list(dict.fromkeys(fill.questions + asked))


def _checks(plan: waves.Plan, fill: _Fill, pls) -> list[str]:
    """What the draft must hold and does not: an item before a prerequisite, an item twice, a pin not honoured."""
    return _order_checks(plan, fill, pls) + _twice(fill) + [
        f"{i}: pinned to s{p.pin}, not placed there" for i, p in pls.items()
        if p.pin in fill.windows and p.status != "composed" and i not in fill.out and fill.at.get(i) != p.pin]


def _order_checks(plan: waves.Plan, fill: _Fill, pls) -> list[str]:
    """A drafted item before one of its prerequisites (a composed item is the plan's fact: a question says it)."""
    drafted = {i: k for i, k in fill.at.items() if pls[i].status != "composed"}
    return [f"{i} (s{k}) before its prerequisite {d} (s{fill.at[d]})" for i, k in drafted.items()
            for d in plan.blockers(i) if fill.at.get(d, 0) > k]


def _twice(fill: _Fill) -> list[str]:
    seen = [i for ids in fill.placed.values() for i in ids]
    return sorted(f"{i} placed {seen.count(i)} times" for i in set(seen) if seen.count(i) > 1)


def _eras(plan: waves.Plan, pls, fill: _Fill) -> list[dict]:
    out = []
    for era in plan.eras:
        stage = str(waves._props(plan.nodes[era]).get("stage_to") or "")
        due = sorted(i for i, p in pls.items() if p.before and p.era == era)
        out.append({"era": era, "stage": stage, "due": len(due),
                    "placed": {i: f"s{fill.at[i]}" for i in due if i in fill.at},
                    "left": [i for i in due if i not in fill.at]})
    return out


def _risks(drafted: list[Wave], cap: dict) -> list[str]:
    out = [f"s{w.seq}: lot {lot['n']} unchecked (no known surface): {', '.join(lot['items'])}"
           for w in drafted for lot in w.lots if not lot["checked"]]
    out += [f"s{w.seq}: over its capacity ({w.size['items']} items, {w.size['points']} points)" for w in drafted
            if w.size["items"] > cap["items"] or w.size["points"] > cap["points"]]
    out.append("sizes are judgement, the forecast uncalibrated: the points are estimates")
    return out


def against(prop: Proposal, path: Path) -> dict:
    """What moved since an earlier ``--json`` proposal: per wave, the items added and removed."""
    old = json.loads(path.read_text(encoding="utf-8"))
    before = {w["seq"]: {r["id"] for r in w["items"]} for w in old.get("waves") or []}
    out = {}
    for w in prop.waves:
        now = {r["id"] for r in w.items}
        was = before.get(w.seq, set())
        if now != was:
            out[f"s{w.seq}"] = {"added": sorted(now - was), "removed": sorted(was - now)}
    return out


def render(prop: Proposal, every: bool = False) -> list[str]:
    cap = prop.capacity
    lines = [f"brain wave propose: {len(prop.waves)} wave(s) after {prop.start}, at zero token, writes nothing; "
             f"capacity {cap['items']} items and {cap['points']} points a wave ({cap['basis']}), "
             f"{cap['quick_wins']} place(s) kept for quick wins"]
    if prop.merged:
        lines.append(f"merged, counted done ({len(prop.merged)}): {', '.join(prop.merged)}")
    for w in prop.waves:
        lines += _wave_lines(w)
    for e in prop.eras:
        lines.append(f"era {e['era']} ({e['stage']}): {e['due']} item(s) due before its exit, "
                     f"{len(e['placed'])} placed, {len(e['left'])} left")
    shown = prop.out if every else prop.out[:OUT_SHOWN]
    lines.append(f"out ({len(prop.out)}" + ("" if every or len(prop.out) <= OUT_SHOWN else
                                            f", the first {OUT_SHOWN}; --all for every one") + "):")
    lines += [f"  {r['id']}: {r['why']}" for r in shown]
    for head, rows in (("questions", prop.questions), ("checks", prop.checks), ("risks", prop.risks)):
        if rows:
            lines.append(f"{head} ({len(rows)}):")
            lines += [f"  {r}" for r in rows]
    for k, d in prop.diff.items():
        lines.append(f"since the earlier proposal, {k}: +{', '.join(d['added']) or '-'}; -{', '.join(d['removed']) or '-'}")
    return lines


def _wave_lines(w: Wave) -> list[str]:
    s = w.size
    out = [f"{w.id} ({w.release or '?'}, {w.kind}): {s['items']}/{s['of_items']} items, "
           f"{s['points']}/{s['of_points']} points" + (f"; doors: {', '.join(w.doors)} (an ADR with Scope and Target "
                                                       "compatibility each)" if w.doors else "")]
    if w.standing:
        out.append(f"  standing: {', '.join(w.standing)} (a batch)")
    for r, ids in enumerate(w.rounds, 1):
        for n in ids:
            lot = w.lots[n - 1]
            out.append(f"  round {r}, lot {n}{'' if lot['checked'] else ' (unchecked)'}: {', '.join(lot['items'])}")
    out += [f"  waits: {x}" for x in w.waits]
    return out
