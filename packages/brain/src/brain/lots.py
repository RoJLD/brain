"""``brain wave plan``: a wave's lots at zero token (wi-brain-wave-lot-planner; the owner's idea of 2026-11-10, lots
that never touch the same file, computed instead of composed by hand: les-brain-lots-composed-by-hand).

**The surface.** Each open item of the wave (brain.waves: part_of it or carried to it) gets its predicted surface from
brain.collisions (:func:`brain.collisions.surface`): the CodeRefs of the features it delivers and of its modules, the
file names its title and props name, and what :data:`brain.collisions.SURFACE_HOOKS` add (wi-brain-touched-surface
will plug the files that similar finished items touched there). Two items meet on a file when one's path is the
other's, or ends with ``/`` and the other's name (``cli.py`` meets ``packages/brain/src/brain/cli.py``).

**Hot files.** Some files nearly every PR touches and only adds to: the READMEs, CHANGELOGs, ``formats.md``,
``FEATURES.md``, ``config.schema.json`` (an optional key) and the changelog fragments of ``changes/`` (:data:`HOT`;
``--hot NAME`` adds more). They never put two items in one lot; the plan lists who shares them, to add and never
rewrite, and to merge origin/main before the push.

**The lots.** Items that meet on a file that is not hot go into one lot (transitively: a lot is a connected group), run
in sequence by one session, in the order of their ``depends_on`` edges, then priority. An item with no known surface is
a lot of its own, said unchecked. A lot that holds a prerequisite of another comes in an earlier round; lots that
depend on each other both ways are merged. Within a round, the lots that unblock the most items come first.

**The size.** A round holds at most the lots that may run at once: the sessions cap in force (brain.governor's, the
project's own if lower, minus the master's session) and the PRs one machine verifies at once (:data:`AT_ONCE`, the
full suite of each running locally; ``--at-once N``). The plan also says what the guards would answer now: the
memory guard's two measures (brain.governor) and the last quota forecast's advice (brain.quota's ``quota.json``,
read through its reader: this module never opens the quota readings itself). While config.json
``usage.guard.wave_quota`` is set (wi-brain-wave-quota-gate; RETRO-5), a round holds at most its ``max_streams`` lots,
and the plan says how many streams fit now (brain.wavegate.room): this session's live streams under
``max_streams``, and the first round's lots, each at the sum of its items' recorded estimates (props.cost_estimate;
none recorded: the median session's), that keep the week's forecast at its reset under ``ask_over_pct``. It prints
and refuses nothing; ``brain next`` shows the current wave's plan in short.

**The quick-win slot.** The plan's head says the wave's quick-win slot (brain.waves.quickwin_slot,
wi-brain-wave-quickwin-slot): about a fifth of its places kept for items of size S with a high value, what fills it
and, while a place is free, the startable quick wins outside the wave that would.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import collisions, governor, quota, resume, wavegate, waves

HOT = ("README.md", "CHANGELOG.md", "FEATURES.md", "formats.md", "config.schema.json", "changes/")
AT_ONCE = 3   # the PRs one machine verifies at once: each runs the whole suite locally, ~10 minutes on all cores
PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


@dataclass
class Unit:
    id: str
    title: str
    status: str
    priority: str
    files: list[str] = field(default_factory=list)      # the predicted surface: paths and names, not hot
    hot: list[str] = field(default_factory=list)        # the hot files it touches
    after: list[str] = field(default_factory=list)      # its open prerequisites in the wave
    outside: list[str] = field(default_factory=list)    # its open prerequisites outside the wave
    usd: float | None = None                             # its recorded estimate (props.cost_estimate's usd=)

    @property
    def known(self) -> bool:
        return bool(self.files or self.hot)


@dataclass
class Lot:
    n: int
    items: list[str]
    files: list[str]
    hot: list[str]
    unblocks: int
    checked: bool
    round: int = 0


@dataclass
class WavePlan:
    wave: str
    wid: str
    units: dict[str, Unit]
    lots: list[Lot]
    rounds: list[list[int]]
    conflicts: list[dict]
    hot: dict[str, list[str]]
    caps: dict
    slot: dict = field(default_factory=dict)   # the wave's quick-win slot (brain.waves.quickwin_slot)

    def as_dict(self) -> dict:
        return {"wave": self.wave, "id": self.wid, "caps": self.caps, "slot": self.slot,
                "rounds": [[asdict(self.lots[n - 1]) for n in r] for r in self.rounds],
                "conflicts": self.conflicts, "hot": self.hot,
                "unknown": sorted(u.id for u in self.units.values() if not u.known),
                "outside": {u.id: u.outside for u in self.units.values() if u.outside}}


def is_hot(path: str, extra: tuple[str, ...] = ()) -> bool:
    """Whether ``path`` is a hot file: its name is one of :data:`HOT` (or ``extra``), or it lies in a folder that one
    ending in ``/`` names (``changes/``). A CodeRef's ``repo:`` before the path is left aside."""
    p = "/" + _split(path)[1].replace("\\", "/").lstrip("/")
    for h in (*HOT, *extra):
        if h.endswith("/") and f"/{h}" in p:
            return True
        if not h.endswith("/") and (p.endswith("/" + h) or p == "/" + h):
            return True
    return False


def _split(entry: str) -> tuple[str, str]:
    """(repo, path) of a surface entry: ``repo:path`` for a CodeRef's, a bare name or path otherwise ('' repo)."""
    repo, sep, path = entry.partition(":")
    return (repo, path) if sep else ("", entry)


def meet(a: str, b: str) -> bool:
    """Whether two surface entries are one file: equal, or one a path that ends with ``/`` and the other; two
    CodeRefs of different repos never meet."""
    (ra, pa), (rb, pb) = _split(a), _split(b)
    if ra and rb and ra != rb:
        return False
    return pa == pb or pa.endswith("/" + pb) or pb.endswith("/" + pa)


def shared(a: Unit, b: Unit) -> list[str]:
    """The files two items both touch, hot ones aside; the longer spelling of each."""
    return sorted({max(x, y, key=len) for x in a.files for y in b.files if meet(x, y)})


def _rank(u: Unit) -> tuple:
    return PRIORITY.get(u.priority, 9), u.id


def _unit(plan: waves.Plan, st: resume.Store, nid: str, extra_hot: tuple[str, ...]) -> Unit:
    """One item with its surface (a CodeRef as ``repo:path``, a name as it is), split into files and hot files."""
    node = st.nodes.get(nid) or plan.nodes.get(nid) or {"id": nid}
    paths, names = collisions.surface(node, st)
    entries = sorted({f"{repo}:{p}" if repo else p for repo, p in paths} | set(names))
    hot = [e for e in entries if is_hot(e, extra_hot)]
    props = node.get("props") or {}
    priority = str(props.get("priority") or "")
    return Unit(nid, str(node.get("title") or ""), plan.status(nid), priority, [e for e in entries if e not in hot],
                hot, usd=wavegate.estimate_usd(str(props.get("cost_estimate") or "")))


def units_of(plan: waves.Plan, st: resume.Store, wid: str, extra_hot: tuple[str, ...] = ()) -> dict[str, Unit]:
    """The wave's open items, each with its surface split into files and hot files, and its open prerequisites."""
    out = {i: _unit(plan, st, i, extra_hot) for i in plan.items_of(wid) if plan.status(i) in waves.OPEN}
    for i, u in out.items():
        u.outside = sorted(d for d in plan.blockers(i) if d not in out)
        u.after = sorted(_inside(plan, i, set(out)))
    return out


def _inside(plan: waves.Plan, nid: str, wave: set[str]) -> set[str]:
    """The wave's open items ``nid`` waits on: its open prerequisites in the wave, and those it reaches through open
    items outside the wave (A after B outside, B after C inside: A comes after C)."""
    found, seen, stack = set(), {nid}, list(plan.blockers(nid))
    while stack:
        d = stack.pop()
        if d in seen:
            continue
        seen.add(d)
        if d in wave:
            found.add(d)
        else:
            stack += plan.blockers(d)
    return found


class _Union:
    def __init__(self, ids):
        self.up = {i: i for i in ids}

    def find(self, i: str) -> str:
        while self.up[i] != i:
            self.up[i] = self.up[self.up[i]]
            i = self.up[i]
        return i

    def join(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.up[max(ra, rb)] = min(ra, rb)

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for i in self.up:
            out.setdefault(self.find(i), []).append(i)
        return out


def _cycles(groups: dict[str, list[str]], units: dict[str, Unit]) -> list[tuple[str, str]]:
    """The pairs of groups to merge: those that depend on each other, directly or through others (each strongly
    connected set of the groups' dependency graph, by Tarjan's algorithm)."""
    of = {i: g for g, ids in groups.items() for i in ids}
    edges = {g: sorted({of[d] for i in ids for d in units[i].after} - {g}) for g, ids in groups.items()}
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    merges: list[tuple[str, str]] = []

    def visit(g: str) -> None:   # the wave's lots are few: recursion depth is no concern
        index[g] = low[g] = len(index)
        stack.append(g)
        on.add(g)
        for h in edges[g]:
            if h not in index:
                visit(h)
                low[g] = min(low[g], low[h])
            elif h in on:
                low[g] = min(low[g], index[h])
        if low[g] == index[g]:
            comp = []
            while True:
                h = stack.pop()
                on.discard(h)
                comp.append(h)
                if h == g:
                    break
            merges.extend((comp[0], h) for h in comp[1:])

    for g in sorted(edges):
        if g not in index:
            visit(g)
    return merges


def _order(ids: list[str], units: dict[str, Unit]) -> list[str]:
    """A lot's items in the order its depends_on edges ask, then by priority; a cycle by priority alone."""
    left, done, out = set(ids), set(), []
    while left:
        ready = sorted((i for i in left if not (set(units[i].after) & left)), key=lambda i: _rank(units[i]))
        pick = ready[0] if ready else min(left, key=lambda i: _rank(units[i]))
        out.append(pick)
        left.discard(pick)
        done.add(pick)
    return out


def lots_of(units: dict[str, Unit]) -> tuple[list[Lot], list[dict]]:
    """The lots (unnumbered rounds) and the predicted conflicts: each pair of items that share a file not hot."""
    u = _Union(sorted(units))
    conflicts = []
    ids = sorted(units)
    for k, a in enumerate(ids):
        for b in ids[k + 1:]:
            files = shared(units[a], units[b])
            if files:
                conflicts.append({"items": [a, b], "files": files})
                u.join(a, b)
    groups = u.groups()
    for a, b in _cycles(groups, units):
        u.join(a, b)
    groups = u.groups()
    lots = []
    for ids_ in groups.values():
        order = _order(ids_, units)
        files = sorted({f for i in order for f in units[i].files})
        hot = sorted({f for i in order for f in units[i].hot})
        unblocks = sum(1 for o in units.values() if o.id not in ids_ and set(o.after) & set(ids_))
        lots.append(Lot(0, order, files, hot, unblocks, all(units[i].known for i in order)))
    return lots, conflicts


def rounds_of(lots: list[Lot], units: dict[str, Unit], at_once: int) -> list[list[Lot]]:
    """The lots in rounds: a lot after the lots that hold its prerequisites, at most ``at_once`` lots a round, the
    lots that unblock the most first, then the checked ones, then by their best priority."""
    of = {i: k for k, lot in enumerate(lots) for i in lot.items}
    needs = {k: {of[d] for i in lot.items for d in units[i].after} - {k} for k, lot in enumerate(lots)}
    level: dict[int, int] = {}

    def depth(k: int) -> int:   # no cycle is left between lots (lots_of merged them)
        if k not in level:
            level[k] = 1 + max((depth(m) for m in needs[k]), default=-1)
        return level[k]

    by: dict[int, list[Lot]] = {}
    for k in range(len(lots)):
        by.setdefault(depth(k), []).append(lots[k])
    out: list[list[Lot]] = []
    step = max(int(at_once), 1)
    for d in sorted(by):
        ranked = sorted(by[d], key=lambda lot: (-lot.unblocks, not lot.checked,
                                                min(_rank(units[i]) for i in lot.items), -len(lot.items)))
        out += [ranked[s:s + step] for s in range(0, len(ranked), step)]
    return out


def caps_in_force(root: Path | None, project: str, at_once: int | None = None) -> dict:
    """What sizes a round, and what the guards would answer now: {at_once, sessions, verify, memory, quota, now}."""
    try:
        lim = governor.caps(governor.settings(str(root or "")), project)
    except Exception:   # noqa: BLE001 - a config that does not load leaves the defaults; the plan still prints
        lim = dict(governor.DEFAULTS)
    children = int(lim["sessions"]) - 1   # the master's own session counts in the cap
    sessions = max(children, 1)           # a plan still has a round of one; ``now`` says none can start
    verify = max(int(at_once), 1) if at_once is not None else AT_ONCE
    try:
        mem = governor.memory_info()
        refused = governor.memory_refusal(mem.get("committed"), mem.get("available_gb"), lim)
        memory = ("refuses a new session now: " if refused else "lets a start through: ") + governor.memory_text(
            mem.get("committed"), mem.get("available_gb"), lim)
    except Exception:   # noqa: BLE001 - a machine whose memory cannot be read
        refused, memory = "", "not read on this machine"
    level, advice = quota_answer(quota.load_status(), datetime.now(timezone.utc))
    wq = lim.get("wave_quota") if lim.get("enabled", True) else None
    streams = int(wq["max_streams"]) if wq and wq.get("max_streams") else None
    lots = min(sessions, verify, streams or sessions)
    now = 0 if refused or level == "none" or children < 1 else lots
    return {"at_once": lots, "sessions": sessions, "verify": verify, "memory": memory, "memory_refuses": bool(refused),
            "sessions_left": max(children, 0), "quota": level, "quota_advice": advice, "now": now,
            "max_streams": streams, "streams": None}


def lot_usd(lot: Lot, units: dict[str, Unit]) -> float | None:
    """A lot's cost: the sum of its items' recorded estimates; None when none of them has one."""
    known = [units[i].usd for i in lot.items if units[i].usd is not None]
    return round(sum(known), 2) if known else None


def streams_now(root: Path | None, caps: dict, first: list[Lot], units: dict[str, Unit]) -> None:
    """While the wave quota gate is on, ``caps["streams"]`` (brain.wavegate.room for this session, the first
    round's lots at their cost) and ``now`` lowered to the streams that fit."""
    try:
        from . import sessions
        me = sessions.here()
        room = wavegate.room(str(root or ""), me["host_id"] or me["session"],
                                  [lot_usd(lot, units) for lot in first] or [None])
    except Exception as exc:   # noqa: BLE001 - a hint: a plan always prints
        caps["streams"] = {"fit": None, "line": f"not known ({type(exc).__name__})"}
        return
    if room is None:
        return
    caps["streams"] = {k: room.get(k) for k in ("fit", "by_quota", "by_streams", "line")}
    if room["fit"] is not None:
        caps["now"] = min(caps["now"], room["fit"])


def quota_answer(fc: dict, now: datetime) -> tuple[str, str]:
    """(level, words) of the last quota forecast (brain.quota's quota.json, through its reader), said as the last
    forecast with its time; a forecast whose window has reset since, or that cannot be read, answers nothing
    ("unknown")."""
    if not fc:
        return "unknown", "no forecast yet (brain usage quota)"
    try:
        resets = quota._dt(fc.get("resets"))
        if resets is not None and resets <= now:
            return "unknown", f"the last forecast ({fc.get('now')}) is from before the window's reset (brain usage quota)"
        level, words = quota.advice(fc)
    except Exception:   # noqa: BLE001 - a quota.json written by hand or by another engine never breaks a plan
        return "unknown", "the last forecast cannot be read (brain usage quota)"
    return level, f"{words} (the last forecast, {fc.get('now') or 'undated'})"


def plan(store: Path, root: Path | None, wave: str = "", project: str = "", at_once: int | None = None,
         hot: tuple[str, ...] = ()) -> WavePlan:
    """The plan of ``wave`` (its release or id; default the current wave, brain next's) in ``store``.
    :class:`ValueError` when the store holds no such wave."""
    pl = waves.load(store, root)
    wid = _wave_id(pl, wave, store)
    units = units_of(pl, resume.Store.load(store), wid, tuple(hot))
    caps = caps_in_force(root, project, at_once)
    lots, conflicts = lots_of(units)
    rounds = rounds_of(lots, units, caps["at_once"])
    if caps["max_streams"] is not None:
        streams_now(root, caps, rounds[0] if rounds else [], units)
    numbered = [lot for group in rounds for lot in group]
    for n, lot in enumerate(numbered, 1):
        lot.n = n
    for r, group in enumerate(rounds, 1):
        for lot in group:
            lot.round = r
    return WavePlan(pl.label(wid), wid, units, numbered, [[lot.n for lot in g] for g in rounds], conflicts,
                    _hot_shared(units, numbered), caps, waves.quickwin_slot(pl, wid))


def _wave_id(pl: waves.Plan, wave: str, store: Path) -> str:
    """The wave named (its release or id), else the current one; :class:`ValueError` without one."""
    if wave:
        wid = pl.resolve(wave) or pl.resolve(wave.removeprefix("wave-"))
        if not wid:
            raise ValueError(f"{wave}: no wave of that release or id in {store}")
        return wid
    pend = waves.pending_waves(pl)
    if not pend:
        raise ValueError(f"no open wave in {store} (brain wave add)")
    return pend[0]


def _hot_shared(units: dict[str, Unit], lots: list[Lot]) -> dict[str, list[str]]:
    """Each hot file that items of two lots or more touch, with those items."""
    lot_of = {i: lot.n for lot in lots for i in lot.items}
    by: dict[str, set[str]] = {}
    for u in units.values():
        for f in u.hot:
            by.setdefault(f, set()).add(u.id)
    return {f: sorted(ids) for f, ids in sorted(by.items()) if len({lot_of[i] for i in ids}) > 1}


def _item(u: Unit) -> str:
    notes = [u.priority] if u.priority else []
    if u.status != "todo":
        notes.append(u.status)
    if u.after:
        notes.append(f"after {', '.join(u.after)}")
    if u.outside:
        notes.append(f"waits on {', '.join(u.outside)} outside the wave")
    return u.id + (f" [{', '.join(notes)}]" if notes else "")


def _files(files: list[str], n: int = 6) -> str:
    return ", ".join(files[:n]) + (f", ... {len(files) - n} more" if len(files) > n else "")


def _lot_lines(wp: WavePlan, lot: Lot) -> list[str]:
    """A lot's two lines: its items in their order, then its files."""
    if not lot.checked:
        what = "unchecked: no known surface"
    else:
        what = f"files: {_files(lot.files)}" if lot.files else "no file but hot ones"
    extra = f"; hot: {_files(lot.hot)}" if lot.hot else ""
    unb = f", unblocks {lot.unblocks}" if lot.unblocks else ""
    return [f"  Lot {lot.n} ({len(lot.items)} item(s){unb}): " + " -> ".join(_item(wp.units[i]) for i in lot.items),
            f"    {what}{extra}"]


def render(wp: WavePlan) -> list[str]:
    c = wp.caps
    lines = [f"Wave {wp.wave} ({wp.wid}): {len(wp.units)} open item(s) in {len(wp.lots)} lot(s) over "
             f"{len(wp.rounds)} round(s) (zero token; brain wave plan)",
             f"At most {c['at_once']} lot(s) a round: the sessions cap in force less the master's ({c['sessions']}), "
             f"the PRs verified at once ({c['verify']}, --at-once)"
             + (f", the streams of one master ({c['max_streams']}, usage.guard.wave_quota)"
                if c.get("max_streams") else ""),
             f"Now: memory guard {c['memory']}; quota: {c['quota_advice']}"
             + ("; the sessions cap leaves no session beside the master's" if not c["sessions_left"] else "")
             + ("; no lot can start now" if not c["now"] else "")]
    if c.get("streams"):
        lines.append(f"Streams that fit now: {c['streams']['line']}")
    line = waves.slot_line(wp.slot, wp.wid)
    if line:
        lines.append(line[:1].upper() + line[1:])
    for r, group in enumerate(wp.rounds, 1):
        lines.append(f"Round {r} ({len(group)} lot(s)):")
        for n in group:
            lines += _lot_lines(wp, wp.lots[n - 1])
    lines.append(f"Predicted conflicts ({len(wp.conflicts)}), the reason two items share a lot:")
    lines += [f"  {' + '.join(x['items'])}: {_files(x['files'])}" for x in wp.conflicts] or ["  none"]
    lines.append(f"Hot files shared across lots ({len(wp.hot)}): add, never rewrite; merge origin/main before the push")
    lines += [f"  {f}: {', '.join(ids)}" for f, ids in wp.hot.items()] or ["  none"]
    unknown = sorted(u.id for u in wp.units.values() if not u.known)
    lines.append(f"No known surface ({len(unknown)}): each a lot of its own, unchecked (a feature's CodeRef, a "
                 f"module or a file named in its title or props gives one; wi-brain-touched-surface)")
    lines += [f"  {', '.join(unknown)}"] if unknown else ["  none"]
    return lines


def summary(wp: WavePlan) -> list[str]:
    """brain next's lines: the first round's lots and the count of the rest."""
    if not wp.rounds:
        return [f"Lots (brain wave plan {wp.wave}): nothing open"]
    first = wp.rounds[0]
    out = [f"Lots (brain wave plan {wp.wave}): {len(wp.lots)} lot(s) over {len(wp.rounds)} round(s); round 1:"]
    out += [f"  Lot {n}: {', '.join(wp.lots[n - 1].items)}" + ("" if wp.lots[n - 1].checked else " (unchecked)")
            for n in first]
    if wp.caps.get("streams"):
        out.append(f"  streams that fit now: {wp.caps['streams']['line']}")
    return out
