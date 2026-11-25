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
quick wins (size S, high value). A window that is a pending wave already composed (``--from`` an earlier one) keeps
its composed items, counted against its capacity, and the plan's id and release for it (the later ones count from it).

**Out.** Before any fill: a blocked item, one with an external blocker, one whose placement is out (owner, later, a
trigger), one placed after an era's exit (« after 1.0 ») with no wave named, one pinned beyond the drafted waves, one
in a cycle of prerequisites (looked for among every open item, composed ones included: a composed item in one stays,
the plan's fact, and its edges inside the wave are dropped for the lots), one whose choice of waves lies beyond them.
Each is listed with its reason.

**The fill**, wave by wave: the items pinned to it first (over the capacity if need be: a question), then their open
prerequisites (taking a place kept for quick wins if need be), then the overdue (a pin or a choice on waves composed
without them, a latest wave before the window, a composed item's prerequisite), the prerequisites of the later pins
and of all these, then those due (a latest wave, « before 1.0 »), then by rank; an item goes in when its
placement allows that wave (its pin, one of its choice's waves, from its earliest), every open ``depends_on``
prerequisite is placed in an earlier wave or in the same one within a chain of :data:`brain.lots.CHAIN_CAP`, every open
item it is placed ``after`` in an earlier wave, and the capacity holds; the order is read again after each item placed.
A latest wave orders and never excludes: a deadline missed is drafted and asked. An item it must go ``with`` follows
it when it can (at once, or once its prerequisite has come in); a pair the draft splits is asked once the fill is done.
A pin still before a prerequisite at the end is asked too. A standing item (``props.standing``, or a debt item,
``props.audit_repo``) is a batch in every wave, never a prerequisite to wait on.

**The lots.** Each wave's items are cut by :func:`brain.lots.cut`, an ``own-lot`` item taken out to a lot of its own,
gathered into :data:`MAX_LOTS` with no cycle between lots, and put in rounds by :func:`brain.lots.rounds_of` with the
caps in force.

**The checks.** No item before a prerequisite (nor in the wave of one it is ``after``, nor drafted while one is in no
drafted wave: a pin's), none twice, every pin and choice within the window honoured, the capacity: what fails is listed
(``checks``), never hidden. ``--against FILE`` (an earlier ``--json``) says what moved.
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


def _prereqs(plan: waves.Plan, pls: dict[str, placement.Placement], i: str) -> list[tuple[str, bool]]:
    """``i``'s open prerequisites, each with ``strict``: its ``depends_on`` blockers (False: the same wave within the
    chain cap), then the open items its placement is ``after`` (True: an earlier wave, « after those items' waves »).
    A standing item is a batch in every wave: never a prerequisite to wait on."""
    p = pls.get(i)
    after = [d for d in (p.after if p else ()) if plan.status(d) not in waves.SATISFIED and not _standing(plan, d)]
    return ([(d, False) for d in plan.blockers(i) if d not in after and not _standing(plan, d)]
            + [(d, True) for d in dict.fromkeys(after)])


def _cycles(plan: waves.Plan, pls: dict[str, placement.Placement], ids: set[str]) -> set[str]:
    """The open items in a cycle of prerequisites (``depends_on`` and ``after``) among ``ids``."""
    found: set[str] = set()
    state: dict[str, int] = {}

    def visit(i: str, path: list[str]) -> None:
        state[i] = 1
        for d, _ in _prereqs(plan, pls, i):
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


def _waves_text(ns) -> str:
    return " or ".join(f"s{n}" for n in ns)


class _Fill:
    """The fill of the windows: where each item goes, what is left out and why, the questions."""

    def __init__(self, plan: waves.Plan, pls: dict[str, placement.Placement], windows: list[int], cap: dict):
        self.plan, self.pls, self.windows, self.cap = plan, pls, windows, cap
        self.at: dict[str, int] = {p.item: p.pin for p in pls.values() if p.status == "composed" and p.pin}
        self.out: dict[str, str] = {}
        self.questions: list[str] = []
        self.placed: dict[int, list[str]] = {k: [] for k in windows}
        for i, w in self.at.items():   # a window that is a pending wave (--from before it): its composed items count
            if w in self.placed:
                self.placed[w].append(i)
        self.room: dict[str, str] = {}   # item -> why it waited (capacity, dependency, window)
        self.pending: list[str] = []
        self.early: list[tuple[str, int]] = []   # pins placed before a prerequisite: asked after the fill if still so

    # -- before the fill --
    def exclude(self, cands: list[str], every: list[str]) -> list[str]:
        """The candidates kept; the others out with their reason. A cycle is looked for among ``every`` open item,
        composed ones included (a cycle through a composed item); its composed items stay, the plan's fact."""
        cyc = _cycles(self.plan, self.pls, set(every) | set(cands))
        keep = []
        for i in cands:
            why = self._why_out(i, cyc)
            if why:
                self.out[i] = why
            else:
                keep.append(i)
        if cyc:
            kept = sorted(i for i in cyc if i in self.at)
            self.questions.append(f"a depends_on cycle: {', '.join(sorted(cyc))} (left out until it is broken"
                                  + (f"; {', '.join(kept)} composed, kept" if kept else "") + ")")
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
        if p.pin is None and p.choice and min(p.choice) > self.windows[-1]:
            return f"a choice of {_waves_text(p.choice)}, beyond the drafted waves"
        return ""

    # -- the fill --
    def choice(self, i: str) -> tuple[int, ...]:
        """The waves of ``i``'s choice it may still take (none: no choice, or every one composed without it)."""
        p = self.pls.get(i)
        if not p or not p.choice or p.pin is not None:
            return ()
        return tuple(c for c in p.choice if c >= self.windows[0])

    def bounds(self, i: str) -> tuple[int, int]:
        """The first and last wave ``i``'s placement allows. A pin bounds both, a choice both (its waves); an overdue
        pin or choice (a wave composed without it) bounds nothing: it comes first. A latest wave bounds nothing
        either: a due item comes early, and a deadline missed is a question, never a reason to leave it out."""
        p = self.pls.get(i)
        lo, hi = self.windows[0], 10 ** 6
        if not p:
            return lo, hi
        if ch := self.choice(i):
            lo, hi = max(lo, min(ch)), max(ch)
        if p.pin is not None and p.pin >= self.windows[0]:
            lo, hi = p.pin, p.pin
        if p.earliest is not None:
            lo = max(lo, p.earliest)
        return lo, hi

    def deps_ok(self, i: str, k: int) -> bool:
        """Every open prerequisite of ``i`` placed before wave ``k``, or a ``depends_on`` one in it within the chain
        cap (an ``after`` one never: after its wave)."""
        why = self.unmet(i, k)
        if why:
            self.room[i] = why
        return not why

    def unmet(self, i: str, k: int) -> str:
        """Why ``i`` may not go in wave ``k`` for its prerequisites ('': it may)."""
        for d, strict in _prereqs(self.plan, self.pls, i):
            w = self.at.get(d)
            if w is None or w > k or (strict and w == k):
                return (f"after: {d} not placed in a wave before s{k}" if strict
                        else f"dependency: {d} not placed before s{k}")
            if w == k and self._chain(d, k) >= lots.CHAIN_CAP:
                return f"dependency: {d}'s chain in s{k} is at the cap ({lots.CHAIN_CAP})"
        return ""

    def _chain(self, i: str, k: int, seen: frozenset = frozenset()) -> int:
        """The longest chain of items in wave ``k`` that ends at ``i`` (a cycle, of composed items, followed once)."""
        here = [d for d in self.plan.blockers(i) if self.at.get(d) == k and d not in seen and d != i]
        return 1 + max((self._chain(d, k, seen | {i}) for d in here), default=0)

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
        for t in self.partners(i):
            if t not in self.at and t in self.pending and self._eligible(t, k) and self.fits(k, t):
                self.put(t, k)

    def partners(self, i: str) -> list[str]:
        """The open items ``i`` goes ``with`` (one done or merged, or standing, a batch in every wave: none)."""
        return [t for t in (self.pls[i].together if i in self.pls else ())
                if self.plan.status(t) in waves.OPEN and not _standing(self.plan, t)]

    def _waiting(self, k: int) -> list[str]:
        """The partners of wave ``k``'s items still to place (one whose prerequisite has just come in may follow)."""
        return [t for x in self.placed[k] for t in self.partners(x) if t not in self.at and t in self.pending]

    def apart(self) -> list[str]:
        """Once the fill is done, each pair placed ``with`` each other that the draft split: one in another wave, in
        none, or out."""
        out, seen = [], set()
        for i in sorted(set(self.at) | set(self.pending)):
            for t in self.partners(i):
                if frozenset((i, t)) not in seen:
                    seen.add(frozenset((i, t)))
                    out += self._split(i, t)
        return out

    def _split(self, i: str, t: str) -> list[str]:
        wi, wt = self.at.get(i), self.at.get(t)
        if wi == wt:
            return []   # together, or neither drafted (each listed out with its reason)
        if wi is None:
            i, t, wi, wt = t, i, wt, wi   # the drafted one first
        if wt is not None:
            return [f"{i} (s{wi}) goes with {t}, drafted in s{wt}"]
        if t in self.out:
            return [f"{i} goes with {t}, which is out ({self.out[t]})"]
        return [f"{i} (s{wi}) goes with {t}, which is in no drafted wave ({self.room.get(t, 'capacity')})"]

    def _eligible(self, i: str, k: int) -> bool:
        lo, hi = self.bounds(i)
        ch = self.choice(i)
        if k < lo or k > hi or (ch and k not in ch):
            self.room.setdefault(i, f"window: from s{lo}" if k < lo else
                                 f"window: a choice of {_waves_text(ch)}" if ch else f"window: s{hi} at the latest")
            return False
        return self.deps_ok(i, k)

    def run(self, cands: list[str]) -> None:
        self.pending = list(cands)
        late = self._late(cands)
        order = self._order(cands, {i for i, _ in late})
        for k in self.windows:
            self._pins(k)
            need = self._needed(k, order)   # the prerequisites of its pins first, before the other first items
            for reserve in (True, False):   # the quick-win places, kept, then given to the rest if none came
                while self._pass(k, need + order, reserve, set(need)):   # a placed item may let its dependents in
                    pass
            self.pending = [i for i in self.pending if i not in self.at]
        self.questions += self._early() + [f"{head}: {self._outcome(i)}" for i, head in late]
        self.questions += self._deadlines(cands) + self.apart()

    def _order(self, cands: list[str], late: set[str]) -> list[str]:
        """The fill's order: first the late items, the items pinned within the window, and their open prerequisites;
        then those due; then by rank."""
        rank = self.plan.ranker.key
        pins = {i for i in cands if (p := self.pls.get(i)) and p.pin in self.windows}
        first = self._lifted(late | pins, set(cands))
        due = {i for i in cands if (p := self.pls.get(i)) and (p.before or p.latest is not None)}
        return sorted(cands, key=lambda i: (i not in first, i not in due, rank(i)))

    def _early(self) -> list[str]:
        """The pins placed before a prerequisite that the fill did not bring in by the end (same wave, chain cap)."""
        return [f"{i} is pinned to s{k}, but {why.split(': ', 1)[1]}" for i, k in self.early
                if (why := self.unmet(i, k))]

    def _late(self, cands: list[str]) -> list[tuple[str, str]]:
        """The items that come first, each a question once the fill is done: pinned to a wave composed without them
        (a pin, a choice), due by a wave before the drafted ones, or waited on by a composed item."""
        first = self.windows[0]
        late: list[tuple[str, str]] = []
        for i in sorted(cands):
            p = self.pls.get(i)
            if not p:
                continue
            if p.pin is not None and p.pin < first:
                late.append((i, f"{i} is pinned to s{p.pin}, which was composed without it"))
            elif p.pin is None and p.choice and max(p.choice) < first:
                late.append((i, f"{i}'s choice of waves, {_waves_text(p.choice)}, was composed without it"))
            elif p.pin is None and p.latest is not None and p.latest < first:
                late.append((i, f"{i} is due by s{p.latest}, before the drafted waves"))
        late += [(d, f"{c} (composed in s{self.at[c]}) waits on {d}, in no wave")
                 for d, c in sorted(self._held(set(cands)).items())]
        return late

    def _lifted(self, late: set[str], cands: set[str]) -> set[str]:
        """The items that come first and their open prerequisites among the candidates, so that none of them waits
        behind lower-ranked items."""
        out: set[str] = set()
        stack = sorted(late)
        while stack:
            i = stack.pop()
            if i in out or i not in cands:
                continue
            out.add(i)
            stack += [d for d, _ in _prereqs(self.plan, self.pls, i)]
        return out

    def _outcome(self, i: str) -> str:
        if i in self.at:
            return f"drafted in s{self.at[i]}, first"
        return f"in no drafted wave ({self.out.get(i) or self.room.get(i, 'capacity')})"

    def _deadlines(self, cands: list[str]) -> list[str]:
        """A latest wave within the window that the draft misses: placed later, or in no wave."""
        out = []
        for i in cands:
            p = self.pls.get(i)
            if not p or p.pin is not None or p.latest is None or p.latest < self.windows[0] or i in self.out:
                continue
            if i not in self.at and p.latest <= self.windows[-1]:
                out.append(f"{i} is due by s{p.latest}: in no drafted wave ({self.room.get(i, 'capacity')})")
            elif self.at.get(i, 0) > p.latest:
                out.append(f"{i} is due by s{p.latest}: no room there, drafted in s{self.at[i]}")
        return out

    def _held(self, cands: set[str]) -> dict[str, str]:
        """The candidates a composed item waits on (prerequisite -> the first composed item that waits): due first."""
        out: dict[str, str] = {}
        for c in sorted(i for i, p in self.pls.items() if p.status == "composed" and i in self.at):
            for d, _ in _prereqs(self.plan, self.pls, c):
                if d in cands:
                    out.setdefault(d, c)
        return out

    def _pins(self, k: int) -> None:
        for i in [i for i in self.pending if (p := self.pls.get(i)) and p.pin == k]:
            if i in self.at:
                continue
            if self.unmet(i, k):   # its prerequisites, lifted, may still come in this wave: asked after the fill
                self.early.append((i, k))
            over = not self.fits(k, i)
            self.put(i, k)
            if over:
                self.questions.append(f"{i} is pinned to s{k}, over its capacity")

    def _needed(self, k: int, order: list[str]) -> list[str]:
        """The open prerequisites of the items pinned to wave ``k`` still to place, in ``order``."""
        pinned = {i for i in self.pending if (p := self.pls.get(i)) and p.pin == k}
        need = self._lifted(pinned, set(self.pending)) - pinned
        return [i for i in order if i in need and i not in self.at]

    def _follow(self, k: int) -> bool:
        """A partner of wave ``k``'s items that could not follow at once, placed now that it may (False: none)."""
        for t in self._waiting(k):
            if self._eligible(t, k) and self.fits(k, t):
                self.put(t, k)
                return True
        return False

    def _reserve(self, i: str, quick: int) -> int:
        """The places still kept for quick wins, for ``i`` (none for a quick win)."""
        return 0 if self.plan.ranker.score(i).quick_win else max(0, self.cap["quick_wins"] - quick)

    def _pass(self, k: int, order: list[str], keep_quick: bool = True, need: set[str] | None = None) -> bool:
        """One item placed in wave ``k``, the first in ``order`` that may go there (False: none). The caller runs it
        again, so that an item first in order whose prerequisite has just come in takes its place before the rest. A
        pin's prerequisite (``need``) takes a place kept for quick wins."""
        if self._follow(k):
            return True
        quick = sum(1 for i in self.placed[k] if self.plan.ranker.score(i).quick_win)
        for i in order:
            if i in self.at or i not in self.pending or not self._eligible(i, k):
                continue
            reserve = 0 if not keep_quick or i in (need or ()) else self._reserve(i, quick)
            if len(self.placed[k]) + reserve >= self.cap["items"] or not self.fits(k, i):
                self.room[i] = "capacity"
                continue
            self.put(i, k)
            return True
        return False


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


def _release(before: str, own: str, doors: bool) -> tuple[str, str]:
    """A window's release and kind: the plan's own label for a wave it has (minor when its X.Y moves on from the one
    before), else the next patch after ``before``, a minor when it holds a door."""
    a, b = waves.release_key(before), waves.release_key(own)
    if b:
        return own, "minor" if (b[:2] != a[:2] if a else doors) else "patch"
    return _next_release(before, doors) or before, "minor" if doors else "patch"


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
    _acyclic(units)
    found = _grouped(plan, _alone(lots.cut(units).lots, units, own), units, own)
    return _numbered(lots.rounds_of(found, units, at_once))


def _acyclic(units: dict) -> None:
    """The wave's order with no cycle: the edges between items that wait on each other (a cycle of composed items,
    the plan's fact, already asked) dropped, since the cutter and :func:`brain.lots.rounds_of` need none."""
    reach = {i: _reach(i, set(units), units) for i in units}
    for i, u in units.items():
        u.after = [d for d in u.after if i not in reach[d]]


def _alone(cut: list, units: dict, own: set[str]) -> list:
    """The cutter's lots, each own-lot item taken out to a lot of its own."""
    found = []
    for lot in cut:
        found += _split_own(lot, units, own) if len(lot.items) > 1 and set(lot.items) & own else [lot]
    return found


def _split_own(lot, units: dict, own: set[str]) -> list:
    """A lot with its own-lot items each taken out alone. When the rest would both wait on the item and be waited on
    by it (a cycle between lots, which :func:`brain.lots.rounds_of` cannot order), the rest is cut in two: what the
    item waits on, and the others."""
    parts, cut_rest = [list(lot.items)], False
    for x in [i for i in lot.items if i in own]:
        part = next(p for p in parts if x in p)
        if len(part) > 1:
            parts.remove(part)
            pieces, cyclic = _take_out(x, part, units)
            parts += pieces
            cut_rest = cut_rest or cyclic
    return _assemble(lot, parts, units, own, cut_rest)


def _assemble(lot, parts: list[list[str]], units: dict, own: set[str], cut_rest: bool) -> list:
    """The lots of ``parts``: each own-lot item alone, then the rest, the cut's lot kept when it was not cut."""
    solo = [p for p in parts if len(p) == 1 and p[0] in own]
    alone = [lots.Lot(0, p, units[p[0]].files, units[p[0]].hot, lot.unblocks, units[p[0]].known) for p in solo]
    rest = [p for p in parts if p and p not in solo]
    if rest and not cut_rest:   # the cut's lot, less its own-lot items
        lot.items = rest[0]
        return alone + [lot]
    return alone + [lots._lot(p, units) for p in rest]


def _take_out(x: str, part: list[str], units: dict) -> tuple[list[list[str]], bool]:
    """``x`` out of ``part``: ([x], the rest) or, when the rest would both wait on ``x`` and be waited on by it, ([x],
    what ``x`` waits on, the others); and whether that cut was needed."""
    rest = [i for i in part if i != x]
    before = _reach(x, set(rest), units)
    after = [i for i in rest if i not in before]
    cyclic = bool(before) and any(x in _reach(i, set(part), units) for i in after)
    return ([[x], [i for i in rest if i in before], after] if cyclic else [[x], rest]), cyclic


def _reach(i: str, within: set[str], units: dict) -> set[str]:
    """The items of ``within`` that ``i`` waits on, directly or through others of ``within``."""
    found: set[str] = set()
    stack = [d for d in units[i].after if d in within]
    while stack:
        d = stack.pop()
        if d not in found:
            found.add(d)
            stack += [e for e in units[d].after if e in within]
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


def _cyclic(parts: list, units: dict) -> bool:
    """Whether lots wait on each other in a cycle (through the items' prerequisites in the wave)."""
    of = {i: k for k, lot in enumerate(parts) for i in lot.items}
    needs = {k: {of[d] for i in lot.items for d in units[i].after if d in of} - {k} for k, lot in enumerate(parts)}
    left = set(needs)
    while left:
        ready = {k for k in left if not needs[k] & left}
        if not ready:
            return True
        left -= ready
    return False


class _Joiner:
    """The wave's lots as they are joined: a join stays within :data:`brain.lots.LOT_CAP` items and never makes two
    lots wait on each other (one that reaches the other through a third: :func:`brain.lots.rounds_of` needs no cycle
    between lots)."""

    def __init__(self, found: list, units: dict):
        self.lots, self.units = list(found), units

    def join(self, a, b):
        """``a`` and ``b`` joined, or None when they may not be."""
        if len(a.items) + len(b.items) > lots.LOT_CAP:
            return None
        ab = _join([a, b])
        trial = [ab] + [x for x in self.lots if x is not a and x is not b]
        if _cyclic(trial, self.units):
            return None
        self.lots = trial
        return ab


def _grouped(plan: waves.Plan, found: list, units: dict, own: set[str]) -> list:
    """The cutter's lots gathered into :data:`MAX_LOTS` sessions at most: lots that share no file may run in one
    session in turn, so lots of one module join first, then the smallest pairs, never over :data:`brain.lots.LOT_CAP`
    items, never a broad lot or an own-lot one, never into a cycle between lots (:class:`_Joiner`)."""
    fixed = [lot for lot in found if lot.broad or set(lot.items) & own]
    free = [lot for lot in found if not any(lot is f for f in fixed)]
    joiner = _Joiner(found, units)

    def module(lot) -> str:
        return str(waves._props(plan.nodes.get(lot.items[0]) or {}).get("module") or "")

    groups: dict[str, list] = {}
    for lot in free:
        groups.setdefault(module(lot) or lot.items[0], []).append(lot)
    merged = _shrink([m for g in groups.values() for m in _pack(g, joiner)], max(MAX_LOTS - len(fixed), 1), joiner)
    out = merged + fixed
    for lot in out:
        lot.items = lots._order(lot.items, units)
    return out


def _shrink(merged: list, most: int, joiner: _Joiner) -> list:
    """The smallest pair that may join, joined, while there are more than ``most`` lots."""
    merged = sorted(merged, key=lambda lot: len(lot.items))
    while len(merged) > most:
        pairs = sorted(((a, b) for n, a in enumerate(merged) for b in merged[n + 1:]),
                       key=lambda ab: len(ab[0].items) + len(ab[1].items))
        pair = next(((a, b, j) for a, b in pairs if (j := joiner.join(a, b)) is not None), None)
        if pair is None:
            break
        a, b, ab = pair
        merged = sorted([ab] + [x for x in merged if x is not a and x is not b], key=lambda lot: len(lot.items))
    return merged


def _pack(group: list, joiner: _Joiner) -> list:
    """One module's lots, joined in turn while they stay within the lot cap and out of a cycle."""
    out: list = []
    for lot in sorted(group, key=lambda x: -len(x.items)):
        for k, o in enumerate(out):
            ab = joiner.join(o, lot)
            if ab is not None:
                out[k] = ab
                break
        else:
            out.append(lot)
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
    standing, every = _open(plan)
    fill.run(fill.exclude([i for i in every if pls[i].status != "composed"], every))
    caps = lots.caps_in_force(root, project, at_once)
    st = resume.Store.load(store)
    drafted = _waves(plan, st, pls, fill, wid, standing, caps["at_once"], cap)
    out = _out(plan, fill)
    questions = _questions(pls, fill)
    return Proposal(plan.label(wid) or wid, cap, drafted, out, questions, _checks(plan, fill, pls), merged,
                    _eras(plan, pls, fill), _risks(drafted, cap))


def _open(plan: waves.Plan) -> tuple[list[str], list[str]]:
    """The open items: (the standing ones, a batch in every wave; the others, composed ones included)."""
    open_ = [i for i in sorted(plan.nodes) if plan.is_item(i) and plan.status(i) in waves.OPEN]
    standing = [i for i in open_ if _standing(plan, i)]
    return standing, [i for i in open_ if i not in standing]


def _here(plan: waves.Plan, by_pos: dict[int, str], k: int) -> tuple[str, str]:
    """The wave the plan has at place ``k`` (--from an earlier one) and its label, or ('', '')."""
    w = by_pos.get(k, "")
    if not w or plan.status(w) == "dropped":
        return "", ""
    return w, plan.labels.get(w, ("", ""))[0]


def _waves(plan, st, pls, fill: _Fill, wid: str, standing: list[str], at_once: int, cap: dict) -> list[Wave]:
    out = []
    label = plan.label(wid)
    by_pos = placement._Ctx.of(plan).by_pos
    for k in fill.windows:
        ids = fill.placed[k]
        doors = [i for i in ids if _door(plan, i)]
        here, own = _here(plan, by_pos, k)   # a wave the plan has there: its own id and label
        label, kind = _release(label, own, bool(doors))
        lot_rows, rounds = _lots(plan, st, ids, {i for i in ids if pls[i].own_lot}, at_once)
        pts = sum(points(plan, i) for i in ids)
        w = Wave(k, here or f"wave-s{k}", label, kind,
                 [_row(plan, i, k, "composed" if pls[i].status == "composed" else "") for i in ids], list(standing),
                 lot_rows, rounds, doors,
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
    """What the draft must hold and does not: an item before a prerequisite, an item twice, a pin or a choice not
    honoured."""
    pins = [f"{i}: pinned to s{p.pin}, not placed there" for i, p in pls.items()
            if p.pin in fill.windows and p.status != "composed" and i not in fill.out and fill.at.get(i) != p.pin
            and not _standing(plan, i)]   # a standing item is a batch in every wave
    choices = [f"{i}: a choice of {_waves_text(fill.choice(i))}, placed in s{fill.at[i]}" for i, p in pls.items()
               if p.status != "composed" and i in fill.at and fill.choice(i) and fill.at[i] not in fill.choice(i)]
    return _order_checks(plan, fill, pls) + _twice(fill) + pins + choices


def _order_checks(plan: waves.Plan, fill: _Fill, pls) -> list[str]:
    """A drafted item before one of its prerequisites, in the same wave as an item it is placed ``after``, or drafted
    while one is in no drafted wave (a pin's; a composed item is the plan's fact: a question says it)."""
    drafted = {i: k for i, k in fill.at.items() if pls[i].status != "composed"}
    return [f"{i} (s{k}) {'not after' if strict else 'before'} its prerequisite {d} "
            + (f"(s{fill.at[d]})" if d in fill.at else "(in no drafted wave)")
            for i, k in drafted.items() for d, strict in _prereqs(plan, pls, i)
            if d not in fill.at or fill.at[d] > k or (strict and fill.at[d] == k)]


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
    before = _earlier(json.loads(path.read_text(encoding="utf-8")), path)
    out = {}
    for w in prop.waves:
        now = {r["id"] for r in w.items}
        was = before.get(w.seq, set())
        if now != was:
            out[f"s{w.seq}"] = {"added": sorted(now - was), "removed": sorted(was - now)}
    return out


def _earlier(old, path: Path) -> dict[int, set[str]]:
    """An earlier ``--json``'s waves: seq -> its items' ids; a file of another shape is a ValueError."""
    waves_ = old.get("waves") if isinstance(old, dict) else None
    if not isinstance(old, dict) or not isinstance(waves_ or [], list):
        raise _not_a_proposal(path)
    found = [(_ids_of(w, path), w) for w in waves_ or []]   # each wave checked before its seq is read
    return {w["seq"]: ids for ids, w in found}


def _not_a_proposal(path: Path) -> ValueError:
    return ValueError(f"--against {path}: not a brain wave propose --json (an object whose waves each carry a seq and "
                      "items with an id)")


def _ids_of(w, path: Path) -> set[str]:
    """One earlier wave's item ids; a wave of another shape is a ValueError."""
    rows = w.get("items") if isinstance(w, dict) else None
    ok = isinstance(w, dict) and isinstance(w.get("seq"), int) and isinstance(rows or [], list)
    if not ok or not all(isinstance(r, dict) and "id" in r for r in rows or []):
        raise _not_a_proposal(path)
    return {str(r["id"]) for r in rows or []}


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
