"""``brain wave plan``: a wave's lots at zero token (wi-brain-wave-lot-planner; the owner's idea of 2026-11-10, lots
that never touch the same file, computed instead of composed by hand: les-brain-lots-composed-by-hand).

**The surface.** Each open item of the wave (brain.waves: part_of it or carried to it) gets its predicted surface from
brain.collisions, weighted (:func:`brain.collisions.weighted`, wi-brain-wave-plan-surfaces): **strong** what says what
it edits (a file or a ``brain.x`` module its title, ``where``, ``size_reason`` or ``files`` name; the CodeRefs of a
narrow feature it delivers; what :data:`brain.collisions.SURFACE_HOOKS` add, where wi-brain-touched-surface will plug
the files similar finished items touched), **weak** what only stands near it (a file its other props name, a spec
document, a broad feature's or its module's CodeRefs). Two entries meet on a file when one's path is the other's, or
ends with ``/`` and the other's name (``cli.py`` meets ``packages/brain/src/brain/cli.py``).

**Hot files.** Some files nearly every PR touches and only adds to: the READMEs, CHANGELOGs, ``formats.md``,
``FEATURES.md``, ``config.schema.json`` (an optional key) and the changelog fragments of ``changes/`` (:data:`HOT`;
``--hot NAME`` adds more), and the files the repos' history shows so (:func:`history_hot`: touched by
:data:`HISTORY_SHARE` of the last :data:`HISTORY_PRS` first-parent commits or more, at least :data:`HISTORY_MIN`,
mostly by additions: the registries every command adds a line to). They never put two items in one lot; the plan lists
who shares them in the lots' order, to add and never rewrite, and to merge origin/main before the push.

**The lots.** Items that meet on a file that is not hot, a strong entry on one side at least, go into one lot
(transitively: a lot is a connected group), run in sequence by one session, in the order of their ``depends_on``
edges, then priority; two weak entries that meet are listed as possible conflicts and join nothing. A lot over
:data:`LOT_CAP` items, or whose longest ``depends_on`` chain is over :data:`CHAIN_CAP`, is split: the links through its
most shared file are cut first (as edge betweenness would), until it fits or nothing links it; each cut file becomes a
merge-order note. A broad item (a surface over :data:`BROAD_FILES` files, or a repo's standing debt item:
``props.audit_repo`` or ``props.standing``) joins no lot: a lot of its own, in the last round when nothing waits on
it. An item with no known surface is a lot of its own, said unchecked. A lot that holds a prerequisite of another
comes in an earlier round; lots that depend on each other both ways are merged. Within a round, the lots that unblock
the most items come first.

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

from . import closemerged, collisions, governor, quota, resume, wavegate, waves

HOT = ("README.md", "CHANGELOG.md", "FEATURES.md", "formats.md", "config.schema.json", "changes/")
HISTORY_PRS = 100     # the last first-parent commits of each repo's default branch read for hot files
HISTORY_SHARE = 0.10  # a file touched by this share of them or more ...
HISTORY_MIN = 5       # ... and by this many at least ...
ADDITIVE = 0.5        # ... with this many lines deleted at most per line added: hot by history
LOT_CAP = 8           # a lot over this many items is split
CHAIN_CAP = 3         # a lot whose longest depends_on chain is over this many items is split
BROAD_FILES = 30      # an item with more strong entries than this is broad: a lot of its own, last
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
    merged: list[str] = field(default_factory=list)      # its merged PRs, when --include-merged keeps it
    strong: list[str] = field(default_factory=list)      # the entries of ``files`` that say what it edits
    broad: bool = False                                  # a lot of its own, last (BROAD_FILES, a standing debt item)

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
    broad: bool = False


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
    merged: dict = field(default_factory=dict)  # merged but not closed (:func:`merged_of`)
    possible: list[dict] = field(default_factory=list)   # weak-weak meetings: listed, never a lot
    cuts: list[dict] = field(default_factory=list)       # the files a split cut: merge-order notes
    history: dict = field(default_factory=dict)          # hot by history (:func:`history_hot`)

    def as_dict(self) -> dict:
        return {"wave": self.wave, "id": self.wid, "caps": self.caps, "slot": self.slot, "merged": self.merged,
                "rounds": [[asdict(self.lots[n - 1]) for n in r] for r in self.rounds],
                "conflicts": self.conflicts, "possible": self.possible, "cuts": self.cuts,
                "history": self.history, "hot": self.hot,
                "unknown": sorted(u.id for u in self.units.values() if not u.known),
                "outside": {u.id: u.outside for u in self.units.values() if u.outside}}


def history_hot(repos: list[tuple[str, Path]], n: int = HISTORY_PRS) -> dict:
    """The files hot by history: in each repo, the last ``n`` first-parent commits of its default branch as last fetched
    (one ``git log --numstat``), each file touched by :data:`HISTORY_SHARE` of them or more (:data:`HISTORY_MIN` at
    least) with :data:`ADDITIVE` lines deleted at most per line added. {"files": {path: {repo, share, prs, added,
    deleted}}, "read": {repo: commits read}, "skipped": {repo: why}}; a repo git cannot read is skipped."""
    out: dict = {"files": {}, "read": {}, "skipped": {}}
    for name, path in repos:
        try:
            end = closemerged._default_end(path)
            log = closemerged._git(path, "log", "--first-parent", "--diff-merges=first-parent", "--no-renames",
                                   "--numstat", f"-n{int(n)}", "--format=%x1e", end)   # %x1e: closemerged.END
        except closemerged.CloseError as exc:
            out["skipped"][name] = str(exc)
            continue
        commits = [c for c in log.split(closemerged.END)[1:]]
        touched: dict[str, list[int]] = {}
        for c in commits:
            for line in c.splitlines():
                parts = line.split("\t")
                if len(parts) != 3:
                    continue
                t = touched.setdefault(parts[2], [0, 0, 0])
                t[0] += 1
                if parts[0].isdigit() and parts[1].isdigit():
                    t[1] += int(parts[0])
                    t[2] += int(parts[1])
        out["read"][name] = len(commits)
        for f, (prs, added, deleted) in sorted(touched.items()):
            if commits and prs >= HISTORY_MIN and prs / len(commits) >= HISTORY_SHARE and deleted <= ADDITIVE * added:
                out["files"].setdefault(f, {"repo": name, "share": round(prs / len(commits), 2), "prs": prs,
                                            "added": added, "deleted": deleted})
    return out


def _hot_by(entry: str, extra: tuple[str, ...], history: tuple[str, ...]) -> bool:
    """Hot: :func:`is_hot` with ``extra``, or one file with a path hot by history (a name meets the path it ends)."""
    return is_hot(entry, extra) or any(meet(entry, h) for h in history)


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
    """The files two items both touch, hot ones aside, a strong entry on one side at least: the reason they share a
    lot; the longer spelling of each."""
    sa, sb = set(a.strong), set(b.strong)
    return sorted({max(x, y, key=len) for x in a.files for y in b.files if meet(x, y) and (x in sa or y in sb)})


def possible(a: Unit, b: Unit) -> list[str]:
    """The files two items meet on through weak entries alone: a possible conflict, listed, never a lot."""
    sa, sb = set(a.strong), set(b.strong)
    return sorted({max(x, y, key=len) for x in a.files if x not in sa for y in b.files if y not in sb
                   and meet(x, y)} - set(shared(a, b)))


def _rank(u: Unit) -> tuple:
    return PRIORITY.get(u.priority, 9), u.id


def _unit(plan: waves.Plan, st: resume.Store, nid: str, extra_hot: tuple[str, ...], history: tuple[str, ...] = (),
          code: dict | None = None) -> Unit:
    """One item with its weighted surface (a CodeRef as ``repo:path``, a name as it is), split into files (its strong
    ones said) and hot files; broad when it is over :data:`BROAD_FILES` files or a standing debt item."""
    node = st.nodes.get(nid) or plan.nodes.get(nid) or {"id": nid}
    strong, weak = collisions.weighted(node, st, code=code)
    entries = sorted(set(strong) | set(weak))
    hot = [e for e in entries if _hot_by(e, extra_hot, history)]
    props = node.get("props") or {}
    priority = str(props.get("priority") or "")
    files = [e for e in entries if e not in hot]
    sure = [e for e in files if e in set(strong)]
    return Unit(nid, str(node.get("title") or ""), plan.status(nid), priority, files, hot,
                usd=wavegate.estimate_usd(str(props.get("cost_estimate") or "")),
                strong=sure, broad=standing(props) or len(sure) > BROAD_FILES)


def standing(props: dict) -> bool:
    """A repo's standing debt item: the one its audit defers into (props.audit_repo), or one said standing."""
    return bool(props.get("audit_repo")) or str(props.get("standing") or "").strip().lower() in ("true", "yes", "1")


def units_of(plan: waves.Plan, st: resume.Store, wid: str, extra_hot: tuple[str, ...] = (),
             history: tuple[str, ...] = ()) -> dict[str, Unit]:
    """The wave's open items, each with its surface split into files and hot files (``history``: the paths hot by
    history), and its open prerequisites."""
    code = collisions.coderefs(st)
    out = {i: _unit(plan, st, i, extra_hot, history, code) for i in plan.items_of(wid) if plan.status(i) in waves.OPEN}
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


@dataclass
class Cut:
    """The lot cutter's answer: the lots (unnumbered rounds), the predicted conflicts left (each pair of items that
    share a file not hot, a strong entry on one side), the possible ones (weak entries alone), the files a split cut."""
    lots: list[Lot]
    conflicts: list[dict]
    possible: list[dict]
    cuts: list[dict]


def lots_of(units: dict[str, Unit]) -> tuple[list[Lot], list[dict]]:
    """The lots (unnumbered rounds) and the predicted conflicts (:func:`cut`'s)."""
    c = cut(units)
    return c.lots, c.conflicts


def chain(ids, units: dict[str, Unit]) -> int:
    """The longest depends_on chain among ``ids``, in items (a cycle counted once through)."""
    ids = set(ids)
    memo: dict[str, int] = {}

    def depth(i: str, seen: frozenset) -> int:
        if i in memo:
            return memo[i]
        d = 1 + max((depth(j, seen | {i}) for j in units[i].after if j in ids and j not in seen), default=0)
        memo[i] = d
        return d
    return max((depth(i, frozenset()) for i in ids), default=0)


def _components(ids: list[str], links: dict[tuple[str, str], list[str]]) -> list[list[str]]:
    u = _Union(sorted(ids))
    for a, b in links:
        u.join(a, b)
    return [sorted(g) for g in u.groups().values()]


def _split_lot(ids: list[str], links: dict[tuple[str, str], list[str]], units: dict[str, Unit],
           cuts: list[dict]) -> list[list[str]]:
    """``ids`` (one component) in components that fit :data:`LOT_CAP` and :data:`CHAIN_CAP`: while one does not, the
    links through its most shared file are cut (the file noted in ``cuts`` with the items that touch it)."""
    out, todo = [], [ids]
    while todo:
        comp = todo.pop()
        inner = _inner(links, comp)
        if not inner or (len(comp) <= LOT_CAP and chain(comp, units) <= CHAIN_CAP):
            out.append(comp)
            continue
        top = _most_shared(inner)
        cuts.append({"file": top, "items": sorted({i for k, v in inner.items() if top in v for i in k})})
        for k in inner:
            links[k] = [f for f in links[k] if f != top]
        todo += _components(comp, _inner(links, comp))
    return out


def _inner(links: dict[tuple[str, str], list[str]], comp: list[str]) -> dict[tuple[str, str], list[str]]:
    """The links left between two items of ``comp``."""
    ids = set(comp)
    return {k: v for k, v in links.items() if v and k[0] in ids and k[1] in ids}


def _most_shared(inner: dict[tuple[str, str], list[str]]) -> str:
    """The file the most links go through (then the first by name): the one a split cuts first."""
    count: dict[str, int] = {}
    for files in inner.values():
        for f in files:
            count[f] = count.get(f, 0) + 1
    return min(count, key=lambda f: (-count[f], f))


def cut(units: dict[str, Unit]) -> Cut:
    """The lots: the items linked by a shared file (:func:`shared`) in connected groups, a broad item alone, each
    group over the caps split (:func:`_split_lot`), the groups that depend on each other both ways merged."""
    ids = sorted(units)
    links, maybe = _pairs(units)
    cuts: list[dict] = []
    groups = [g for comp in _components(ids, links) for g in _split_lot(comp, links, units, cuts)]
    u = _Union(ids)
    for g in groups:
        for i in g[1:]:
            u.join(g[0], i)
    for a, b in _cycles(u.groups(), units):
        u.join(a, b)
    lots = [_lot(ids_, units) for ids_ in u.groups().values()]
    conflicts = [{"items": list(k), "files": v} for k, v in sorted(links.items()) if v]
    return Cut(lots, conflicts, maybe, cuts)


def _pairs(units: dict[str, Unit]) -> tuple[dict[tuple[str, str], list[str]], list[dict]]:
    """(the links: each pair of items a shared file joins, the possible conflicts: the pairs weak entries alone meet,
    and the pairs with a broad item, which joins nothing)."""
    ids = sorted(units)
    links: dict[tuple[str, str], list[str]] = {}
    maybe = []
    for k, a in enumerate(ids):
        for b in ids[k + 1:]:
            files, weak = shared(units[a], units[b]), possible(units[a], units[b])
            if units[a].broad or units[b].broad:
                if files or weak:
                    maybe.append({"items": [a, b], "files": sorted(set(files + weak)), "broad": True})
                continue
            if files:
                links[(a, b)] = files
            if weak:
                maybe.append({"items": [a, b], "files": weak})
    return links, maybe


def _lot(ids: list[str], units: dict[str, Unit]) -> Lot:
    """A lot of ``ids`` (unnumbered): its items in their order, its files, its hot files, what it unblocks."""
    order = _order(ids, units)
    unblocks = sum(1 for o in units.values() if o.id not in ids and set(o.after) & set(ids))
    return Lot(0, order, sorted({f for i in order for f in units[i].files}),
               sorted({f for i in order for f in units[i].hot}), unblocks, all(units[i].known for i in order),
               broad=all(units[i].broad for i in order))


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
    last = 1 + max((depth(k) for k in range(len(lots)) if not lots[k].broad), default=-1)
    for k in range(len(lots)):   # a broad lot nothing waits on: after every other round
        tail = lots[k].broad and not any(k in needs[m] for m in needs)
        by.setdefault(max(depth(k), last) if tail else depth(k), []).append(lots[k])
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
        refused = governor.memory_refusal(mem.get("committed"), mem.get("available_gb"), lim,
                                          mem.get("commit_free_gb"))
        memory = ("refuses a new session now: " if refused else "lets a start through: ") + governor.memory_text(
            mem.get("committed"), mem.get("available_gb"), lim, mem.get("commit_free_gb"))
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


def merged_of(pl: waves.Plan, wid: str, repos: list[tuple[str, Path]]) -> tuple[dict, dict[str, list[str]]]:
    """(what the plan says of them, item -> its merged PRs): the items merged but not closed (brain.closemerged's
    mapping, git only: the PRs merged in ``repos`` since the last tag before the wave's release, by changelog fragment
    or an item id in the title), the wave's and the others (a prerequisite outside the wave), with the ranges read and
    the repos not read (their items stay open)."""
    ov = closemerged.overlay(pl, repos, pl.label(wid))
    found = {i: [p.ref for p in prs] for i, prs in ov.to_close.items()}
    members = set(pl.items_of(wid))
    return {"release": ov.version, "items": {i: v for i, v in found.items() if i in members},
            "outside": {i: v for i, v in found.items() if i not in members}, "ranges": ov.ranges,
            "skipped": ov.skipped, "counted": "done"}, found


def as_done(pl: waves.Plan, ids) -> waves.Plan:
    """The plan with ``ids`` counted done: out of the open items, the lots and the quick-win slot's candidates, and
    satisfied as a prerequisite."""
    ids = set(ids)
    if not ids:
        return pl
    nodes = {k: ({**n, "status": "done"} if k in ids else n) for k, n in pl.nodes.items()}
    return waves.build(nodes, pl.edges, pl.ddrs)


def plan(store: Path, root: Path | None, wave: str = "", project: str = "", at_once: int | None = None,
         hot: tuple[str, ...] = (), repos: list[tuple[str, Path]] | None = None,
         include_merged: bool = False, merged: tuple[dict, dict] | None = None,
         read_merged: bool = True) -> WavePlan:
    """The plan of ``wave`` (its release or id; default the current wave, brain next's) in ``store``. With ``repos``
    ((name, checkout)), the items their merged PRs deliver and not closed yet count as done (:func:`merged_of`; or
    ``merged``, that pair already read; none read when ``read_merged`` is false), unless ``include_merged`` keeps them
    in the lots, said merged; and the files hot by their history count hot (:func:`history_hot`).
    :class:`ValueError` when the store holds no such wave."""
    pl = waves.load(store, root)
    wid = _wave_id(pl, wave, store)
    if merged is None and repos and read_merged:
        merged = merged_of(pl, wid, repos)
    pl, said = _overlaid(pl, merged, include_merged)
    history = history_hot(repos) if repos else {}
    units = units_of(pl, resume.Store.load(store), wid, tuple(hot), tuple((history.get("files") or {})))
    for i, u in units.items():
        u.merged = (said.get("items") or {}).get(i, [])
    caps = caps_in_force(root, project, at_once)
    c = cut(units)
    rounds = rounds_of(c.lots, units, caps["at_once"])
    if caps["max_streams"] is not None:
        streams_now(root, caps, rounds[0] if rounds else [], units)
    numbered = _numbered(rounds)
    return WavePlan(pl.label(wid), wid, units, numbered, [[lot.n for lot in g] for g in rounds], c.conflicts,
                    _hot_shared(units, numbered), caps, waves.quickwin_slot(pl, wid), said, c.possible, c.cuts,
                    _history_of(history, units))


def _numbered(rounds: list[list[Lot]]) -> list[Lot]:
    """The lots in the rounds' order, each numbered and given its round."""
    numbered = [lot for group in rounds for lot in group]
    for n, lot in enumerate(numbered, 1):
        lot.n = n
    for r, group in enumerate(rounds, 1):
        for lot in group:
            lot.round = r
    return numbered


def _history_of(history: dict, units: dict[str, Unit]) -> dict:
    """What the plan says of the history read: the hot-by-history files this wave's items touch, the repos read and
    those skipped."""
    if not history:
        return {}
    touched = {h: v for h, v in (history.get("files") or {}).items()
               if any(meet(e, h) for u in units.values() for e in u.hot)}
    return {"files": touched, "read": history.get("read") or {}, "skipped": history.get("skipped") or {}}


def _overlaid(pl: waves.Plan, merged: tuple[dict, dict] | None, include_merged: bool) -> tuple[waves.Plan, dict]:
    """(the plan the lots are cut from, what the plan says of the merged items): them counted done, or kept open and
    said so with ``include_merged``."""
    if not merged:
        return pl, {}
    said, found = dict(merged[0]), merged[1]
    if include_merged:
        said["counted"] = "open"
        return pl, said
    return as_done(pl, found), said


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
    return {f: sorted(ids, key=lambda i: (lot_of[i], i)) for f, ids in sorted(by.items())
            if len({lot_of[i] for i in ids}) > 1}   # in the lots' order: the merge order


def _item(u: Unit) -> str:
    notes = [u.priority] if u.priority else []
    if u.status != "todo":
        notes.append(u.status)
    if u.merged:
        notes.append(f"merged: {', '.join(u.merged)}")
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
    unb += ", broad: alone" if lot.broad else ""
    return [f"  Lot {lot.n} ({len(lot.items)} item(s){unb}): " + " -> ".join(_item(wp.units[i]) for i in lot.items),
            f"    {what}{extra}"]


def merged_lines(wp: WavePlan) -> list[str]:
    """The plan's lines on what merged and is not closed yet: the wave's items (out of the lots, or in them with
    --include-merged), the prerequisites outside the wave counted satisfied, the repos not read."""
    m = wp.merged
    if not m:
        return []
    items, outside = m.get("items") or {}, m.get("outside") or {}
    how = ("still in the lots (--include-merged)" if m.get("counted") == "open"
           else "out of the lots, counted done")
    lines = [f"Merged, to close ({len(items)}): " + (", ".join(f"{i} ({', '.join(v)})" for i, v in items.items())
                                                    or "none") + (f"; {how}" if items else "")
             + (f"; brain wave close-merged {m['release']} --write" if items else "")]
    if outside:
        what = "counted open" if m.get("counted") == "open" else "satisfied as prerequisites"
        lines.append(f"  merged outside the wave, {what} ({len(outside)}): " + ", ".join(sorted(outside)))
    for repo, why in (m.get("skipped") or {}).items():
        lines.append(f"  merged PRs not read in {repo}: {why} (its items stay open)")
    return lines


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
    lines += merged_lines(wp)
    line = waves.slot_line(wp.slot, wp.wid)
    if line:
        lines.append(line[:1].upper() + line[1:])
    for r, group in enumerate(wp.rounds, 1):
        lines.append(f"Round {r} ({len(group)} lot(s)):")
        for n in group:
            lines += _lot_lines(wp, wp.lots[n - 1])
    lines.append(f"Predicted conflicts ({len(wp.conflicts)}), the reason two items share a lot:")
    lines += [f"  {' + '.join(x['items'])}: {_files(x['files'])}" for x in wp.conflicts] or ["  none"]
    lines += _list(f"Possible conflicts ({len(wp.possible)}), weak entries alone (a spec, a broad feature, a module, "
                   "context props; or a broad item): no lot joined", [
                       f"  {' + '.join(x['items'])}: {_files(x['files'], 3)}" for x in wp.possible])
    lines += _cut_lines(wp) + _hot_lines(wp)
    unknown = sorted(u.id for u in wp.units.values() if not u.known)
    lines.append(f"No known surface ({len(unknown)}): each a lot of its own, unchecked (a feature's CodeRef, a "
                 f"module or a file named in its title or props gives one; wi-brain-touched-surface)")
    lines += [f"  {', '.join(unknown)}"] if unknown else ["  none"]
    return lines


def _cut_lines(wp: WavePlan) -> list[str]:
    """The lots split: each file cut, with the items that touch it in the lots' order (the merge order)."""
    if not wp.cuts:
        return []
    of = {i: lot.n for lot in wp.lots for i in lot.items}
    return [f"Lots split ({len(wp.cuts)} file(s) cut, over {LOT_CAP} items or a chain over {CHAIN_CAP}): merge in "
            "the lots' order, origin/main merged before each push"] + [
        f"  {x['file']}: " + ", ".join(f"{i} (lot {of[i]})" for i in sorted(x["items"], key=lambda i: (of[i], i)))
        for x in wp.cuts]


def _hot_lines(wp: WavePlan) -> list[str]:
    """The hot files shared across lots, in the lots' order; the files hot by history; the repos not read."""
    lines = [f"Hot files shared across lots ({len(wp.hot)}): add, never rewrite; merge origin/main before the push, "
             "in the lots' order"]
    lines += [f"  {f}: {', '.join(ids)}" for f, ids in wp.hot.items()] or ["  none"]
    h = wp.history or {}
    if h.get("files"):
        lines.append(f"Hot by history ({len(h['files'])} the wave touches; {HISTORY_SHARE:.0%} of the last "
                     f"{HISTORY_PRS} commits or more, mostly added): "
                     + ", ".join(f"{f} ({v['share']:.0%})" for f, v in h["files"].items()))
    return lines + [f"  history not read in {r}: {why}" for r, why in (h.get("skipped") or {}).items()]


def _list(head: str, rows: list[str], n: int = 12) -> list[str]:
    """A section: its head, at most ``n`` rows and the count of the rest, or « none »."""
    return [head] + (rows[:n] + ([f"  ... {len(rows) - n} more (--json)"] if len(rows) > n else []) or ["  none"])


def summary(wp: WavePlan) -> list[str]:
    """brain next's lines: the first round's lots and the count of the rest."""
    if not wp.rounds:
        return [f"Lots (brain wave plan {wp.wave}): nothing open"]
    first = wp.rounds[0]
    n_merged = len((wp.merged or {}).get("items") or {})
    merged = f", {n_merged} merged to close apart" if n_merged and wp.merged.get("counted") == "done" else ""
    out = [f"Lots (brain wave plan {wp.wave}): {len(wp.lots)} lot(s) over {len(wp.rounds)} round(s){merged}; "
           "round 1:"]
    out += [f"  Lot {n}: {', '.join(wp.lots[n - 1].items)}" + ("" if wp.lots[n - 1].checked else " (unchecked)")
            for n in first]
    if wp.caps.get("streams"):
        out.append(f"  streams that fit now: {wp.caps['streams']['line']}")
    return out
