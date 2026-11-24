"""The order of the milestones (wi-brain-milestone-order; spec-brain-cockpit-ux2 §4.3.3, UX-12; spec-brain-plan-views
§3.5 and §8, S7): the path of the Milestones tab and ``brain milestone path``, read at zero token from the graph and the
forecast's ``<BRAIN_HOME>/forecast/<project>/latest.json``, never recomputed.

No edge links two milestones by default, so the order is derived from their items:
- **a derived arc** A → B when an item of B depends on an item of A (``depends_on``, the items directly ``part_of``
  the thematic milestones: a wave and an era are not on the path), weighted by its pairs of items. By default a pair
  counts while it still waits (neither item done nor dropped: the live waits); ``history`` counts the done pairs too,
  the order the work took;
- **a declared arc** wins: ``brain item link ms-b depends_on ms-a`` puts A before B, and a derived arc the other way
  (B → A) is overruled (``overruled``, never drawn);
- **a knot** is a mutual wait: a strongly connected component of two milestones or more. Its milestones share a
  node ``⟦a ⇄ b⟧`` on the path, and ``--check`` lists each one with its pairs in each direction and how to settle it
  (declare an order, or cut the items).

``layers`` gives the ranks (rank 1: nothing before it; a node's rank is the longest chain of arcs before it, plus
one), the weighted arcs, the knots, the milestones of no arc (``unlinked``) and the chain to the latest p50 (``chain``:
from the linked milestone whose p50 is latest, back through the predecessor whose p50 is latest at each step; without
a forecast, the longest chain of ranks). It is a public contract (``V``; ADR of wi-brain-milestone-order):
``brain milestone path --json`` prints it, the Path view and its text twin draw it, and the PERT view
(wi-brain-tui-pert-view) and the HTML views read it; the readers ignore the keys they do not know.

The drawing, from ``WIDE`` columns: the ranks as columns, left to right, the milestones of a rank in parallel on their
rows, each with its items done out of its live items and its p50 (« reached » and its day once reached), ``─▶`` when it
has a milestone after it in the next rank and « ↳ after X » for an arc that skips a rank; the chain marked ``◆``.
Narrower (or more ranks than fit), a tree: each milestone with the milestones that wait on it as its children, a
repeat shown ``↗``. The legacy console (``TERM=linux``) gets words (UX-13).
"""

from __future__ import annotations

from datetime import date

from . import planviews, resume

V = 1                 # the JSON's version: a new key is additive, a changed meaning moves it
WIDE = 120            # the lanes from here, a tree under it
COL_MIN = 22          # a lane's column at least; more ranks than fit: the tree
COL_MAX = 32
OFF_PATH = ("wave", "era")   # the milestones of these kinds are not on the path (brain.waves, the eras)
GLYPHS = {"arrow": "─▶", "knot": ("⟦", " ⇄ ", "⟧"), "chain": "◆ ", "after": "↳ after ", "repeat": "↗ ",
          "reached": "✓ "}
WORDS = {"arrow": "->", "knot": ("[", " <-> ", "]"), "chain": "* ", "after": "after ", "repeat": "^ ",
         "reached": "reached "}
GONE = ("done", "dropped")


def _kind(n: dict) -> str:
    return str((n.get("props") or {}).get("kind") or "")


def on_path(st: resume.Store) -> dict[str, dict]:
    """The milestones on the path: neither dropped nor a wave nor an era, by id."""
    return {m["id"]: m for m in st.of_type("Milestone") if m.get("status") != "dropped" and _kind(m) not in OFF_PATH}


def _members(st: resume.Store, ms: dict[str, dict]) -> dict[str, set[str]]:
    """{work item: the path's milestones it is directly part of}."""
    out: dict[str, set[str]] = {}
    for e in st.edges:
        if e.get("type") == "part_of" and e.get("to") in ms and (st.nodes.get(e.get("from")) or {}).get("type") == \
                "WorkItem":
            out.setdefault(e["from"], set()).add(e["to"])
    return out


def derived(st: resume.Store, ms: dict[str, dict], history: bool = False) -> dict[tuple[str, str], list[list[str]]]:
    """{(A, B): [[the item of B that waits, the item of A it waits on], ...]}: an item of B depends on an item of A;
    a pair counts while both items are open (``history``: the done pairs too; a dropped item never)."""
    member = _members(st, ms)
    out: dict[tuple[str, str], list[list[str]]] = {}
    seen: set[tuple[str, str]] = set()
    for e in st.edges:
        if e.get("type") != "depends_on":
            continue
        x, y = e.get("from"), e.get("to")
        if (x, y) in seen or x not in member or y not in member:
            continue
        seen.add((x, y))
        sx, sy = st.status(x), st.status(y)
        if "dropped" in (sx, sy) or (not history and (sx in GONE or sy in GONE)):
            continue
        for b in member[x]:
            for a in member[y]:
                if a != b:
                    out.setdefault((a, b), []).append([x, y])
    return {k: sorted(v) for k, v in out.items()}


def declared(st: resume.Store, ms: dict[str, dict]) -> set[tuple[str, str]]:
    """{(A, B)}: B depends_on A, both on the path (``brain item link B depends_on A``)."""
    return {(e["to"], e["from"]) for e in st.edges
            if e.get("type") == "depends_on" and e.get("from") in ms and e.get("to") in ms and e["from"] != e["to"]}


def _arcs(st: resume.Store, ms: dict[str, dict], history: bool) -> tuple[list[dict], list[dict]]:
    """(the arcs, the derived arcs a declared one overrules), each sorted by its ends."""
    der, dec = derived(st, ms, history), declared(st, ms)
    arcs, overruled = [], []
    for a, b in sorted(set(der) | dec):
        pairs = der.get((a, b), [])
        arc = {"from": a, "to": b, "pairs": len(pairs), "items": pairs, "declared": (a, b) in dec}
        if not arc["declared"] and (b, a) in dec:
            overruled.append({**arc, "by": f"{a} depends_on {b}"})
        else:
            arcs.append(arc)
    return arcs, overruled


def _sccs(nodes: list[str], succ: dict[str, set[str]]) -> list[list[str]]:
    """The strongly connected components (Tarjan, without recursion), each sorted."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(sorted(succ.get(root, ()))))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            nxt = next(it, None)
            if nxt is not None:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(sorted(succ.get(nxt, ())))))
                elif nxt in on:
                    low[v] = min(low[v], index[nxt])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(sorted(comp))
    return out


def knot_id(members: list[str]) -> str:
    return "knot:" + "+".join(sorted(members))


def _forecast(mid: str, fc: dict | None) -> tuple[str, float | None, str]:
    """(its p50 day, its p50 work hours, why it has no date) from the forecast's row of a milestone."""
    f = planviews._forecast_of(mid, fc) or {}
    hours = ((f.get("work") or {}).get("hours") or {}).get("p50")
    why = planviews._undated(f) if f.get("shown") == "undated" else ""
    return (str((f.get("dates") or {}).get("p50") or ""), float(hours) if isinstance(hours, (int, float)) else None,
            why)


def _short(mid: str, project: str) -> str:
    return planviews._short(mid, project)


def _milestone(st: resume.Store, m: dict, fc: dict | None, project: str) -> dict:
    live = [i for i in st.milestone_items(m["id"]) if st.status(i) != "dropped"]
    props = m.get("props") or {}
    p50, hours, why = _forecast(m["id"], fc)
    return {"id": m["id"], "name": _short(m["id"], project), "title": str(m.get("title") or ""),
            "state": str(m.get("status") or ""), "done": sum(1 for i in live if st.status(i) == "done"),
            "items": len(live), "p50": p50, "hours": hours, "undated": why,
            "reached": str(props.get("reached") or "")[:10]}


def _knots(arcs: list[dict]) -> tuple[dict[str, str], list[dict]]:
    """({milestone of an arc: its node}, the knots): each strongly connected component of the arcs is a node, named by
    its milestone alone or, of several, a knot with the arcs inside it."""
    succ: dict[str, set[str]] = {}
    for a in arcs:
        succ.setdefault(a["from"], set()).add(a["to"])
    linked = sorted({a["from"] for a in arcs} | {a["to"] for a in arcs})
    node_of: dict[str, str] = {}
    knots = []
    for comp in _sccs(linked, succ):
        nid = knot_id(comp) if len(comp) > 1 else comp[0]
        node_of.update(dict.fromkeys(comp, nid))
        if len(comp) > 1:
            inside = [a for a in arcs if a["from"] in comp and a["to"] in comp]
            knots.append({"id": nid, "members": comp, "arcs": inside, "declared": any(a["declared"] for a in inside)})
    return node_of, knots


def layers(st: resume.Store, fc: dict | None, project: str = "", history: bool = False) -> dict:
    """The path of one project's milestones (see the module's doc): ``{v, project, history, as_of, forecast,
    milestones, arcs, overruled, knots, nodes, ranks, chain, chain_hours, unlinked}``; ``nodes`` the path's nodes (a
    milestone, or a knot of several), each with its ``rank``, the nodes just before it (``before``) and after it
    (``after_this``), those before it over a rank (``after``: « ↳ after X »)."""
    ms = on_path(st)
    arcs, overruled = _arcs(st, ms, history)
    node_of, knots = _knots(arcs)
    rows = {mid: {**_milestone(st, ms[mid], fc, project), "node": node_of.get(mid, "")} for mid in sorted(ms)}
    nodes = _nodes(rows, knots, arcs, node_of)
    _rank(nodes)
    ranks = _ranks(nodes)
    for k in knots:
        k["rank"] = nodes[k["id"]]["rank"]
    chain, weight = _chain(nodes, ranks)
    return {"v": V, "project": project, "history": history, "as_of": (fc or {}).get("as_of"),
            "forecast": bool(fc), "milestones": list(rows.values()), "arcs": arcs, "overruled": overruled,
            "knots": knots, "nodes": [nodes[n] for r in ranks for n in r], "ranks": ranks,
            "chain": chain, "chain_hours": weight, "unlinked": [m for m in sorted(ms) if m not in node_of]}


NODE_KEYS = ("name", "state", "done", "items", "p50", "hours", "undated", "reached")


def _knot_node(k: dict, rows: dict[str, dict]) -> dict:
    """A knot's node: its members' counts and p50 work summed, its p50 their latest, reached once all are."""
    ms = [rows[m] for m in k["members"]]
    hours = [r["hours"] for r in ms if r["hours"] is not None]
    return {"id": k["id"], "kind": "knot", "members": k["members"], "name": " ⇄ ".join(r["name"] for r in ms),
            "state": "reached" if all(r["state"] == "reached" for r in ms) else "pending",
            "done": sum(r["done"] for r in ms), "items": sum(r["items"] for r in ms),
            "p50": max(r["p50"] for r in ms), "hours": sum(hours) if hours else None,
            "undated": "; ".join(f"{r['name']} {r['undated']}" for r in ms if r["undated"]), "reached": ""}


def _nodes(rows: dict[str, dict], knots: list[dict], arcs: list[dict], node_of: dict[str, str]) -> dict[str, dict]:
    """The path's nodes by id: a milestone of an arc, or a knot; each with the nodes just before and after it."""
    out = {mid: {"id": mid, "kind": "milestone", "members": [mid], **{k: rows[mid][k] for k in NODE_KEYS}}
           for mid, nid in node_of.items() if nid == mid}
    out.update({k["id"]: _knot_node(k, rows) for k in knots})
    for n in out.values():
        n.update(before=set(), after_this=set(), pairs_in=0)
    for a in arcs:
        s, t = node_of[a["from"]], node_of[a["to"]]
        if s != t:
            out[t]["before"].add(s)
            out[s]["after_this"].add(t)
            out[t]["pairs_in"] += a["pairs"]
    return out


def _rank(nodes: dict[str, dict]) -> None:
    """Each node's rank (Kahn's order on the condensed graph, which has no cycle): 1 with nothing before it, else one
    more than the highest before it; then ``after``: the nodes before it over a rank."""
    indeg = {n: len(x["before"]) for n, x in nodes.items()}
    todo = sorted(n for n, d in indeg.items() if d == 0)
    for n in todo:
        nodes[n]["rank"] = 1
    while todo:
        n = todo.pop(0)
        for t in sorted(nodes[n]["after_this"]):
            nodes[t]["rank"] = max(nodes[t].get("rank", 1), nodes[n]["rank"] + 1)
            indeg[t] -= 1
            if indeg[t] == 0:
                todo.append(t)
    for x in nodes.values():
        x["after"] = sorted(b for b in x["before"] if nodes[b]["rank"] < x["rank"] - 1)
        x["before"], x["after_this"] = sorted(x["before"]), sorted(x["after_this"])


def _ranks(nodes: dict[str, dict]) -> list[list[str]]:
    """The nodes of each rank, the first rank first: each in the order of the row its first node before it sits on
    (so a lane reads left to right), then by p50, then by id."""
    out: list[list[str]] = []
    top = max((x["rank"] for x in nodes.values()), default=0)
    pos: dict[str, int] = {}
    for r in range(1, top + 1):
        here = [n for n, x in nodes.items() if x["rank"] == r]
        here.sort(key=lambda n: (min((pos[b] for b in nodes[n]["before"] if b in pos), default=10 ** 6),
                                 nodes[n]["p50"] or "9999", n))
        for k, n in enumerate(here):
            pos[n] = k
        out.append(here)
    return out


def _chain(nodes: dict[str, dict], ranks: list[list[str]]) -> tuple[list[str], float | None]:
    """The longest chain of p50 work (the critical one): the path whose open milestones' p50 work hours (the
    forecast's, a knot's summed) add up to the most, first node first, and that sum; without a forecast's hours, the
    longest chain by its milestones (the sum None). A reached node weighs nothing; ([], None) when all are reached."""
    timed = any(x["hours"] is not None for x in nodes.values())

    def weight(x: dict) -> float:
        if x["state"] == "reached":
            return 0.0
        return (x["hours"] or 0.0) if timed else 1.0
    best: dict[str, tuple[float, int, str]] = {}
    back: dict[str, str] = {}
    for rank in ranks:   # a node's nodes before it sit in lower ranks
        for n in rank:
            x = nodes[n]
            prev = max(x["before"], key=lambda b: best[b], default="")
            base = best[prev] if prev else (0.0, 0, "")
            best[n] = (base[0] + weight(x), base[1] + (x["state"] != "reached"), n)
            if prev:
                back[n] = prev
    live = [n for n in best if nodes[n]["state"] != "reached"]
    if not live:
        return [], None
    end = max(live, key=lambda n: best[n])
    chain = [end]
    while chain[-1] in back:
        chain.append(back[chain[-1]])
    return chain[::-1], (round(best[end][0], 1) if timed else None)


# --- the check: the knots to settle ---

def problems(lay: dict) -> list[str]:
    """What ``brain milestone path --check`` refuses: each knot (a mutual wait), its pairs each way and how to settle
    it; [] when the path is a DAG."""
    return [line for k in lay.get("knots") or [] for line in knot_lines(k, lay.get("project") or "")]


def knot_lines(k: dict, project: str = "") -> list[str]:
    """A knot's lines: its members, each arc inside it with its pairs (the items that wait, and on what), and the two
    ways to settle it."""
    names = [_short(m, project) for m in k["members"]]
    out = [f"knot {' ⇄ '.join(names)}: a mutual wait (rank {k.get('rank', '?')})"
           + ("; a declared order is part of it" if k.get("declared") else "")]
    for a in k["arcs"]:
        what = "declared" if a["declared"] and not a["pairs"] else f"{a['pairs']} pair(s)" + (
            ", declared" if a["declared"] else "")
        pairs = ", ".join(f"{x} waits on {y}" for x, y in a["items"][:4]) + (" …" if len(a["items"]) > 4 else "")
        out.append(f"  {_short(a['from'], project)} before {_short(a['to'], project)}: {what}"
                   + (f" ({pairs})" if pairs else ""))
    a, b = k["members"][0], k["members"][1]
    out.append(f"  settle: declare an order (brain item link {b} depends_on {a}: {_short(a, project)} first), or cut "
               "an item's depends_on, or move an item to the other milestone")
    return out


# --- the drawing, shared by the Path view and its text twin ---

def _sym(plain: bool) -> dict:
    return WORDS if plain else GLYPHS


def _md(day: str) -> str:
    try:
        d = date.fromisoformat(str(day)[:10])
    except ValueError:
        return ""
    return f"{d:%b} {d.day}"


def _fit(text_: str, room: int) -> str:
    return text_ if len(text_) <= room else (text_[:max(0, room - 1)] + "…" if room > 0 else "")


def _name(x: dict, plain: bool, room: int = 0) -> str:
    """A node's name: a milestone's short id; a knot's members in its brackets, each cut to share ``room`` (0: whole)."""
    if x["kind"] != "knot":
        return _fit(x["name"], room) if room else x["name"]
    lo, mid, hi = _sym(plain)["knot"]
    parts = x["name"].split(" ⇄ ")
    if room:
        each = (room - len(lo) - len(hi) - len(mid) * (len(parts) - 1)) // len(parts)
        if each < 4:   # too many to name in the cell: their count (the tail and the detail name them)
            return _fit(f"{lo}{len(parts)} milestones{hi}", room)
        parts = [_fit(p, each) for p in parts]
    return lo + mid.join(parts) + hi


def _label(x: dict, chain: set[str], plain: bool, room: int = 0) -> str:
    """A node's first line: ``◆`` on the chain, ``✓`` once reached, its name and its items done out of its live
    items, within ``room`` columns (0: whole)."""
    s = _sym(plain)
    head = (s["chain"] if x["id"] in chain else "") + (s["reached"] if x["state"] == "reached" else "")
    counts = f" {x['done']}/{x['items']}"
    return head + _name(x, plain, max(6, room - len(head) - len(counts)) if room else 0) + counts


def _when(x: dict) -> str:
    """A node's date: « reached » and its day, its p50, or why the forecast gives it none."""
    if x["state"] == "reached":
        return f"reached {_md(x['reached'])}".strip()
    return f"p50 {_md(x['p50'])}" if x["p50"] else (x.get("undated") or "")


def _after(x: dict, names: dict[str, str], plain: bool) -> str:
    """« ↳ after X »: the nodes before it over a rank."""
    return (_sym(plain)["after"] + ", ".join(names[b] for b in x["after"])) if x["after"] else ""


def _names(lay: dict, plain: bool) -> dict[str, str]:
    return {n["id"]: _name(n, plain) for n in lay.get("nodes") or []}


def lanes_fit(lay: dict, width: int, columns: int | None = None) -> bool:
    """The lanes when the screen has ``WIDE`` columns (``columns``, else ``width``) and each rank gets ``COL_MIN`` of
    the ``width`` drawn, else the tree."""
    return (width if columns is None else columns) >= WIDE and len(lay.get("ranks") or []) * COL_MIN <= width


def grid(lay: dict, width: int = WIDE, plain: bool | None = None, columns: int | None = None) -> dict:
    """The path as cells: ``{mode: lanes|tree, col, head, rows, tail}``. A lanes row is one cell per rank, ``(node id
    or "", [its lines])``: its label (with ``─▶`` when a node after it sits in the next rank), its date, and « ↳ after
    X » when a row has one; a tree row is ``(node id, line)``. ``head`` the ranks' row, ``tail`` the milestones of no
    arc, the knots to settle and the legend; ``columns`` the screen's (``lanes_fit``)."""
    plain = planviews.words() if plain is None else plain
    ranks = lay.get("ranks") or []
    tail = _tail(lay, plain)
    if not ranks:
        return {"mode": "lanes", "col": COL_MIN, "head": [], "rows": [], "tail": tail}
    if not lanes_fit(lay, width, columns):
        return {"mode": "tree", "col": 0, "head": [], "rows": _tree(lay, plain), "tail": tail}
    col = max(COL_MIN, min(COL_MAX, width // len(ranks)))
    head = "".join(f"rank {r}".ljust(col) for r in range(1, len(ranks) + 1)).rstrip()
    return {"mode": "lanes", "col": col, "head": [head], "rows": _lanes(lay, col, plain), "tail": tail}


def _lanes(lay: dict, col: int, plain: bool) -> list[list[tuple[str, list[str]]]]:
    """The lanes' rows: the row ``i`` holds the ``i``-th node of each rank; three lines when one of them has a
    « ↳ after X », else two."""
    ranks = lay["ranks"]
    nodes = {n["id"]: n for n in lay.get("nodes") or []}
    ctx = {"chain": set(lay.get("chain") or []), "names": _names(lay, plain), "plain": plain, "col": col}
    rows = []
    for i in range(max(len(r) for r in ranks)):
        cells = [nodes[ids[i]] if i < len(ids) else None for ids in ranks]
        three = any(x and x["after"] for x in cells)
        rows.append([_cell(x, ranks[r + 1] if r + 1 < len(ranks) else [], three, ctx) if x else
                     ("", ["", "", ""] if three else ["", ""]) for r, x in enumerate(cells)])
    return rows


def _cell(x: dict, next_rank: list[str], three: bool, ctx: dict) -> tuple[str, list[str]]:
    """A node's cell: its label (``─▶`` to the next rank's column when a node after it sits there), its date, and
    (``three``) its « ↳ after X »."""
    plain, col = ctx["plain"], ctx["col"]
    arrow = _sym(plain)["arrow"]
    more = any(t in next_rank for t in x["after_this"])
    room = col - 1 - (len(arrow) + 2 if more else 0)
    one = _label(x, ctx["chain"], plain, room)
    if more:
        one = one + " " + ("-" if plain else "─") * (room - len(one)) + arrow
    cell = [one, "  " + _fit(_when(x), col - 3)]
    if three:
        cell.append("  " + _fit(_after(x, ctx["names"], plain), col - 3))
    return x["id"], cell


def _tree(lay: dict, plain: bool) -> list:
    """Each rank-1 node with the nodes that wait on it as its children, a node met again shown ``↗`` (a repeat)."""
    s = _sym(plain)
    nodes = {n["id"]: n for n in lay.get("nodes") or []}
    chain, names = set(lay.get("chain") or []), _names(lay, plain)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def walk(ids: list[str], prefix: str) -> None:
        for k, nid in enumerate(ids):
            last = k == len(ids) - 1
            branch = ("`-- " if last else "|-- ") if plain else ("└── " if last else "├── ")
            x = nodes[nid]
            if nid in seen:
                out.append((nid, f"{prefix}{branch}{s['repeat']}{names[nid]}"))
                continue
            seen.add(nid)
            when = _when(x)
            out.append((nid, f"{prefix}{branch}{_label(x, chain, plain)}" + (f"  {when}" if when else "")))
            walk(x["after_this"], prefix + ("    " if last else ("|   " if plain else "│   ")))
    walk(lay["ranks"][0], "")
    return out


def _loose(lay: dict, plain: bool) -> list[str]:
    """The tail's line of the milestones of no arc."""
    rows = {m["id"]: m for m in lay.get("milestones") or []}
    done = _sym(plain)["reached"]
    loose = [rows[m] for m in lay.get("unlinked") or []]
    return ["no arc: " + " · ".join(f"{done if m['state'] == 'reached' else ''}{m['name']} {m['done']}/{m['items']}"
                                    for m in loose)] if loose else []


def _knots_named(lay: dict, plain: bool) -> list[str]:
    """The tail's line of the knots to settle, each named in full."""
    knots = lay.get("knots") or []
    project = lay.get("project") or ""
    named = ", ".join(_name({"kind": "knot", "name": " ⇄ ".join(_short(m, project) for m in k["members"])}, plain)
                      for k in knots)
    return [f"{len(knots)} mutual wait(s) to settle: {named} (brain milestone path --check)"] if knots else []


def _tail(lay: dict, plain: bool) -> list[str]:
    """Under the path: the milestones of no arc, the knots to settle, the arcs overruled, the legend."""
    s = _sym(plain)
    over = [f"{len(lay['overruled'])} derived arc(s) overruled by a declared order"] if lay.get("overruled") else []
    hours = lay.get("chain_hours")
    legend = (f"{s['chain'].strip()} the longest chain of p50 work (critical" + (f", {hours:g} h" if hours else "")
              + f") · {s['knot'][1].strip()} a mutual wait · {s['after'].strip()} an arc over a rank"
              + ("" if lay.get("forecast") else " · no forecast yet: brain forecast"))
    return [*_loose(lay, plain), *_knots_named(lay, plain), *over, legend]


def heading(lay: dict) -> str:
    """The path's line of counts: its milestones, its arcs and from what, its knots, its ranks."""
    what = "every pair, the done ones too" if lay.get("history") else "the live waits"
    return (f"{len(lay.get('milestones') or [])} milestone(s), {len(lay.get('arcs') or [])} arc(s) from {what}, "
            f"{len(lay.get('knots') or [])} mutual wait(s), {len(lay.get('ranks') or [])} rank(s)")


def text(lay: dict, width: int = WIDE, plain: bool | None = None, columns: int | None = None) -> list[str]:
    """One project's path drawn (``grid``): the lanes, each row on its lines, or the tree; then the tail."""
    g = grid(lay, width, plain, columns)
    out = list(g["head"])
    if g["mode"] == "lanes":
        for row in g["rows"]:
            for k in range(len(row[0][1])):
                out.append("".join(cell[1][k].ljust(g["col"]) for cell in row).rstrip())
    else:
        out += [line for _, line in g["rows"]]
    if not g["rows"]:
        out.append("no arc between two milestones: no item of one waits on an item of another")
    return [line[:width].rstrip() for line in out] + g["tail"]


def lines(panel: dict | None, width: int = WIDE, plain: bool | None = None) -> list[str]:
    """The text twin of the Path view (``brain tui --once --tab milestones --view path``): each project's path."""
    groups = (panel or {}).get("projects") or []
    out = ["Milestones · Path"]
    for g in groups:
        if "error" in g:
            out.append(f"  {g['project']}: error: {g['error']}")
            continue
        lay = g.get("path") or {}
        out.append(f"  {g['project']}: {heading(lay)}" if len(groups) > 1 else f"  {heading(lay)}")
        out += ["  " + line for line in text(lay, width - 2, plain, columns=width)]
    if not groups:
        out.append("  no project read yet")
    return out
