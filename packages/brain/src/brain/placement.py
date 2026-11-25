"""Organ placement (wi-brain-organ-placement, ADR of the owner's answers OG-1 to OG-3): every node's organ, the module
of the registry it serves (brain.modules), derived from its edges with its evidence. Zero token; nothing here writes.

A node placed by hand carries ``props.module`` (the items, the features, and the few nodes no edge reaches: a rule, a
hook, a skill, a plugin, an MCP server). Every other node gets its organ from its neighbours, one hop away, along the
edges that say what a node belongs to (:data:`EDGES`), in either direction: each neighbour placed by hand on a module
of the registry gives that module one vote, the evidence keeping which edge carried it. The first module wins when it
has at least twice the votes of the second (:data:`MAJORITY`, a clear majority); otherwise the node is split, and with
no vote it is unplaced. Placement is a distribution: each module's weight is its share of the votes.

A hand placement overrides the votes, which are still counted: when they give another module of the registry a clear
majority of at least :data:`CONTRADICT` votes, the hand placement is contradicted (a gap to look at, never changed by
the engine; a single link, a hook part of its plugin, is no evidence against a choice). A hand ``none`` (the
brain's own process, outside the tree) is never contradicted, and a hand module the registry does not know is brain
check's to report (brain.modules); neither gives a vote.

One hop from a hand placement only: a derived placement gives no vote, so the result never depends on the order nodes
are read, and a second hop (the records placed through what they are ``about``) is left to a later slice. No persisted
format: the placements are computed when they are read (``brain modules``, its view, ``brain item show``, ``brain
features show``), from the store as ``brain sync`` left it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# The edges that say what a node belongs to (spec of the organ graph, § 2.3), read in both directions.
EDGES = ("documented_in", "implemented_by", "tested_by", "specified_by", "decided_by", "enforced_by", "delivers",
         "learned_from", "led_to", "part_of")
MAJORITY = 2   # the first module needs MAJORITY times the votes of the second to place a node
CONTRADICT = 2   # the votes a module needs to contradict a hand placement: one link is no evidence against a choice
NONE = "none"   # brain.modules.NONE: a hand placement outside the tree
STATES = ("hand", "contradicted", "derived", "split", "unplaced")


@dataclass(frozen=True)
class Placement:
    """One node's organ: ``state`` one of :data:`STATES`, ``organ`` the module it is placed on ('' when split or
    unplaced), ``hand`` its ``props.module`` ('' without), ``votes`` {module: {edge type: count}}."""
    node: str
    type: str
    state: str
    organ: str = ""
    hand: str = ""
    votes: dict[str, dict[str, int]] = field(default_factory=dict)

    def tally(self) -> list[tuple[str, int]]:
        """(module, votes), the most voted first, then by id."""
        return sorted(((m, sum(e.values())) for m, e in self.votes.items()), key=lambda mv: (-mv[1], mv[0]))

    def total(self) -> int:
        return sum(n for _, n in self.tally())

    def weights(self) -> dict[str, float]:
        """{module: its share of the votes}, rounded to two decimals, the most voted first."""
        total = self.total()
        return {m: round(n / total, 2) for m, n in self.tally()} if total else {}

    def to_json(self) -> dict:
        return {"node": self.node, "type": self.type, "state": self.state, "organ": self.organ, "hand": self.hand,
                "votes": {m: dict(sorted(e.items())) for m, e in sorted(self.votes.items())},
                "weights": self.weights()}


def _module(g, nid: str) -> str:
    """A node's hand placement: its ``props.module``, '' without."""
    props = g.nodes[nid].get("props")
    return str(props.get("module") or "").strip() if isinstance(props, dict) else ""


def _votes(g, nid: str, known: set[str]) -> dict[str, dict[str, int]]:
    """{module: {edge type: count}} of the neighbours of ``nid`` placed by hand on a module of ``known``, along
    :data:`EDGES` in either direction; another store's node never votes."""
    found: dict[str, Counter] = {}
    ends = [(d, e) for _, d, e in g.out_edges(nid, data="type")] + [(s, e) for s, _, e in g.in_edges(nid, data="type")]
    for other, etype in ends:
        if etype not in EDGES or other == nid or g.nodes[other].get("foreign"):
            continue   # another store's node: its module is of another registry, never a vote here
        mod = _module(g, other)
        if mod in known:
            found.setdefault(mod, Counter())[etype] += 1
    return {m: dict(c) for m, c in found.items()}


def clear(tally: list[tuple[str, int]]) -> str:
    """The module a clear majority of ``tally`` (:meth:`Placement.tally`) places, '' for none or a split."""
    if not tally:
        return ""
    if len(tally) == 1 or tally[0][1] >= MAJORITY * tally[1][1]:
        return tally[0][0]
    return ""


def place(g, nid: str, known: set[str]) -> Placement:
    """The placement of node ``nid`` of the research_graph graph ``g``, against the registry's ids ``known``."""
    ntype = str(g.nodes[nid].get("type") or "")
    hand, votes = _module(g, nid), _votes(g, nid, known)
    p = Placement(nid, ntype, "unplaced", votes=votes)
    winner = clear(p.tally())
    if hand:
        against = hand in known and winner and winner != hand and dict(p.tally())[winner] >= CONTRADICT
        state = "contradicted" if against else "hand"
        return Placement(nid, ntype, state, organ=hand, hand=hand, votes=votes)
    if winner:
        return Placement(nid, ntype, "derived", organ=winner, votes=votes)
    return Placement(nid, ntype, "split" if votes else "unplaced", votes=votes)


def own_nodes(g) -> list[str]:
    """The store's own nodes (not another store's an edge names), sorted."""
    return sorted(n for n, d in g.nodes(data=True) if not d.get("foreign") and d.get("type"))


def place_all(g, known: set[str]) -> dict[str, Placement]:
    """{node id: its placement} of every node the store holds."""
    return {n: place(g, n, known) for n in own_nodes(g)}


def by_type(placed: dict[str, Placement]) -> dict[str, dict[str, int]]:
    """{node type: {nodes, and a count per state of :data:`STATES`}}, by type."""
    out: dict[str, dict[str, int]] = {}
    for p in placed.values():
        row = out.setdefault(p.type, {"nodes": 0, **{s: 0 for s in STATES}})
        row["nodes"] += 1
        row[p.state] += 1
    return dict(sorted(out.items()))


def load(store: Path, root: Path | None = None):
    """The store's graph (research_graph), with the other stores' nodes its edges name; None when it does not load
    (brain check says why)."""
    from research_graph.loader import ValidationError, load_store
    try:
        from . import crossstore
        foreign = crossstore.foreign_nodes(root, store)
    except (OSError, ValueError):   # an unreadable projects registry: the store alone
        foreign = None
    try:
        return load_store(store, foreign=foreign)
    except (ValidationError, OSError, ValueError):
        return None


def data(g, known: set[str]) -> dict:
    """brain modules --json's ``placement``: the counts by type, and the hand placements the votes contradict."""
    placed = place_all(g, known)
    return {"edges": list(EDGES), "majority": MAJORITY, "contradict": CONTRADICT, "by_type": by_type(placed),
            "contradicted": [p.to_json() for p in placed.values() if p.state == "contradicted"]}


def _evidence(p: Placement) -> str:
    """« D8 7: documented_in 5, delivers 2; D11 2: documented_in 2 »."""
    return "; ".join(f"{m} {n}: " + ", ".join(f"{e} {c}" for e, c in sorted(p.votes[m].items(),
                                                                          key=lambda ec: (-ec[1], ec[0])))
                     for m, n in p.tally())


def _named(mod: str, names: dict[str, str]) -> str:
    return f"{mod} {names[mod]}" if names.get(mod) else mod


def line(p: Placement, names: dict[str, str] | None = None) -> str:
    """The organ line of ``brain item show`` and ``brain features show``; ``names`` {module: its name}."""
    names = names or {}
    total, ev = p.total(), _evidence(p)
    if p.state in ("hand", "contradicted"):
        if p.hand == NONE:
            return "organ: none, by hand (outside the tree)" + (f"; its links: {ev}" if ev else "")
        head = f"organ: {_named(p.organ, names)}, by hand (props.module)"
        if p.state == "contradicted":
            winner = p.tally()[0]
            return (f"{head}; contradicted: its links give {winner[0]} a clear majority ({winner[1]} of {total}: "
                    f"{ev})")
        return head + (f"; its links: {ev}" if ev else "")
    if p.state == "derived":
        return f"organ: {_named(p.organ, names)}, derived from {dict(p.tally())[p.organ]} of {total} link(s) ({ev})"
    if p.state == "split":
        return f"organ: split, no clear majority ({ev}); props.module places it"
    return "organ: unplaced (no link to a node placed by hand); props.module places it"


def view_lines(g, known: set[str], names: dict[str, str] | None = None) -> list[str]:
    """The module view's section (brain.modules.render): the counts by node type, then the hand placements the votes
    contradict; a store whose graph does not load (``g`` None) gets one line."""
    out = ["", "## Placement", ""]
    if g is None:
        return out + ["Not derived: the store's graph does not load (brain check says why)."]
    placed = place_all(g, known)
    out += [f"Every node's organ, derived from the modules of its neighbours placed by hand (`props.module`), one hop "
            f"along {', '.join(EDGES)}: the first module places it when it has at least {MAJORITY} times the votes "
            f"of the second. A hand `props.module` overrides; it is contradicted when the votes give another module "
            f"that majority with at least {CONTRADICT} votes (brain.placement).", "",
            "| Type | Nodes | By hand | Derived | Split | Unplaced | Contradicted |", "|---|---|---|---|---|---|---|"]
    rows = by_type(placed)
    for t, r in rows.items():
        out.append(f"| {t} | {r['nodes']} | {r['hand'] + r['contradicted']} | {r['derived']} | {r['split']} | "
                   f"{r['unplaced']} | {r['contradicted']} |")
    tot = {k: sum(r[k] for r in rows.values()) for k in ("nodes", *STATES)}
    out.append(f"| **All** | {tot['nodes']} | {tot['hand'] + tot['contradicted']} | {tot['derived']} | "
               f"{tot['split']} | {tot['unplaced']} | {tot['contradicted']} |")
    wrong = [p for p in placed.values() if p.state == "contradicted"]
    out += ["", "### Hand placements the votes contradict", ""]
    out += [f"- `{p.node}` ({p.type}): {_named(p.hand, names or {})} by hand, its links {_evidence(p)}"
            for p in wrong] or ["None."]
    return out
