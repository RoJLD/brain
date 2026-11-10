from __future__ import annotations

import networkx as nx

# The node attribute naming the store that holds a node an edge of this store points to (loader.load_store's
# ``foreign``): such a node has no ``type`` of this store (every listing of the store's own nodes leaves it out), its
# type kept as ``foreign_type``, its title and status as its own store has them.
FOREIGN = "foreign"


def kind(g: nx.DiGraph, nid: str) -> str | None:
    """A node's type: its own, or the one its store gives it when it is another store's (:data:`FOREIGN`)."""
    a = g.nodes[nid]
    return a.get("type") or a.get("foreign_type")


def store_of(g: nx.DiGraph, nid: str) -> str | None:
    """The label of the other store that holds ``nid``, None for a node of this store."""
    return g.nodes[nid].get(FOREIGN)


def label(g: nx.DiGraph, nid: str) -> str:
    """How a view names a node: its id, and for another store's node that store's label (``wi-x (parent:graph)``)."""
    store = store_of(g, nid)
    return f"{nid} ({store})" if store else nid


class ResearchGraph:
    def __init__(self, graph: nx.DiGraph):
        self.g = graph

    def _status(self, nid: str) -> str | None:
        return self.g.nodes[nid].get("status")

    def _type(self, nid: str) -> str | None:
        return kind(self.g, nid)

    def gating_verdicts(self, nid: str) -> list[str]:
        return [d for _, d, a in self.g.out_edges(nid, data=True) if a.get("type") == "gated_by"]

    def _gate_satisfied(self, vid: str) -> bool:
        # A gate counts as satisfied only if it is a Verdict that is validated.
        return self._type(vid) == "Verdict" and self._status(vid) == "validated"

    def frontier(self) -> list[str]:
        out = []
        for nid, attrs in self.g.nodes(data=True):
            if attrs.get("type") != "Experiment":
                continue
            if attrs.get("status") not in {"planned", "open"}:
                continue
            if all(self._gate_satisfied(v) for v in self.gating_verdicts(nid)):
                out.append(nid)
        return sorted(out)

    def gated(self) -> list[str]:
        out = []
        for nid, attrs in self.g.nodes(data=True):
            if attrs.get("type") != "Experiment":
                continue
            gates = self.gating_verdicts(nid)
            if gates and any(not self._gate_satisfied(v) for v in gates):
                out.append(nid)
        return sorted(out)

    def provenance(self, nid: str) -> list[str]:
        if nid not in self.g:
            raise KeyError(nid)
        undirected = self.g.to_undirected(as_view=True)
        return sorted(nx.node_connected_component(undirected, nid))

    def supersedes_chain(self, nid: str) -> list[str]:
        chain = [nid]
        cur = nid
        visited = {nid}
        while True:
            nxt = [
                d for _, d, a in self.g.out_edges(cur, data=True) if a.get("type") == "supersedes"
            ]
            if not nxt:
                break
            cur = nxt[0]
            if cur in visited:
                break
            visited.add(cur)
            chain.append(cur)
        return chain


# --- layered graph (work / data / risk / platform) ---

# Edge types whose source relies on their target ("A depends on B"); the impact of B reaches A.
RELIES_ON_TARGET = frozenset({
    "depends_on", "specified_by", "provided_by", "derived_from", "hosted_in", "settles_in",
    "settles_on", "exposes", "uses", "gated_by", "tests", "exploits", "decided_by", "instantiates",
    # operations overlay (a sibling repo's ops/graph)
    "deploys", "executed_by", "uses_account", "limited_by", "runs_on", "documented_in",
    # code layer: a node relies on the code it is implemented by
    "implemented_by",
})
# Edge types whose target relies on their source ("A is part of / produces B"); the impact of A reaches B.
RELIES_ON_SOURCE = frozenset({"part_of", "delivers", "produces"})

# Statuses meaning "this prerequisite is satisfied".
SATISFIED = frozenset({"done", "reached", "validated", "active", "live"})
WORK_OPEN = frozenset({"todo", "doing", "blocked"})


class LayeredGraph(ResearchGraph):
    """Queries over the work, data, risk and platform layers of the research graph."""

    def _reliance(self) -> nx.DiGraph:
        """Directed graph with an edge A -> B whenever A relies on B, whatever the edge's own direction."""
        out = nx.DiGraph()
        out.add_nodes_from(self.g.nodes)
        for s, d, a in self.g.edges(data=True):
            t = a.get("type")
            if t in RELIES_ON_TARGET:
                out.add_edge(s, d, type=t)
            elif t in RELIES_ON_SOURCE:
                out.add_edge(d, s, type=t)
        return out

    def _satisfied(self, nid: str) -> bool:
        return self._status(nid) in SATISFIED

    def prerequisites(self, nid: str) -> list[str]:
        """Direct prerequisites of a work item: its ``depends_on`` / ``gated_by`` targets."""
        return sorted(
            d for _, d, a in self.g.out_edges(nid, data=True) if a.get("type") in {"depends_on", "gated_by"}
        )

    def blockers(self, nid: str) -> list[str]:
        return [p for p in self.prerequisites(nid) if not self._satisfied(p)]

    def work_frontier(self) -> list[str]:
        """``todo`` work items whose prerequisites are all satisfied: what can start now."""
        return sorted(
            n for n, a in self.g.nodes(data=True)
            if a.get("type") == "WorkItem" and a.get("status") == "todo" and not self.blockers(n)
        )

    def blocked(self) -> dict[str, list[str]]:
        """Open work items that cannot proceed, mapped to their blockers (``external`` if marked blocked)."""
        out: dict[str, list[str]] = {}
        for n, a in self.g.nodes(data=True):
            if a.get("type") != "WorkItem" or a.get("status") not in WORK_OPEN:
                continue
            why = self.blockers(n)
            if a.get("status") == "blocked":
                why = why + ["external"]
            if why:
                out[n] = why
        return dict(sorted(out.items()))

    def milestone_items(self, mid: str) -> list[str]:
        """Work items attached to a milestone, recursively through sub-milestones."""
        items: set[str] = set()
        stack = [mid]
        seen = {mid}
        while stack:
            cur = stack.pop()
            for s, _, a in self.g.in_edges(cur, data=True):
                if a.get("type") != "part_of" or s in seen:
                    continue
                seen.add(s)
                if self._type(s) == "Milestone":
                    stack.append(s)
                else:
                    items.add(s)
        return sorted(items)

    def milestone(self, mid: str) -> dict:
        """Progress of a milestone and its remaining critical path (longest chain of open items)."""
        if mid not in self.g:
            raise KeyError(mid)
        items = self.milestone_items(mid)
        counts: dict[str, int] = {}
        for n in items:
            counts[self._status(n) or "?"] = counts.get(self._status(n) or "?", 0) + 1
        open_items = [n for n in items if self._status(n) in WORK_OPEN]
        sub = nx.DiGraph()
        sub.add_nodes_from(open_items)
        for s, d, a in self.g.edges(data=True):
            if a.get("type") == "depends_on" and s in sub and d in sub:
                sub.add_edge(d, s)  # prerequisite first
        path = nx.dag_longest_path(sub) if nx.is_directed_acyclic_graph(sub) else []
        props = self.g.nodes[mid].get("props") or {}
        return {
            "milestone": mid,
            "status": self._status(mid),
            "trigger": props.get("trigger"),
            "items": len(items),
            "by_status": dict(sorted(counts.items())),
            "critical_path": path,
            "cycle": not nx.is_directed_acyclic_graph(sub),
        }

    def impact(self, nid: str) -> dict[str, list[str]]:
        """Everything that transitively relies on ``nid``, grouped by layer."""
        if nid not in self.g:
            raise KeyError(nid)
        reliance = self._reliance()
        dependents = nx.ancestors(reliance, nid)
        out: dict[str, list[str]] = {}
        for n in dependents:   # another store's node: under that store's label, its layer being that store's
            key = f"store {store_of(self.g, n)}" if store_of(self.g, n) else self.g.nodes[n].get("layer") or "research"
            out.setdefault(key, []).append(n)
        return {k: sorted(v) for k, v in sorted(out.items())}

    def layer(self, name: str) -> list[str]:
        return sorted(n for n, a in self.g.nodes(data=True)
                      if not a.get(FOREIGN) and (a.get("layer") or "research") == name)

    # --- decisions layer ---

    DECISION_TYPES = frozenset({"ADR", "SDR"})

    def _is_decision(self, nid: str) -> bool:
        return self._type(nid) in self.DECISION_TYPES

    def current_decision(self, did: str) -> str:
        """The newest decision in the supersedes chain: the one superseding ``did`` (transitively), if any."""
        cur, seen = did, {did}
        while True:
            newer = [
                s for s, _, a in self.g.in_edges(cur, data=True)
                if a.get("type") == "supersedes" and self._is_decision(s) and s not in seen
            ]
            if not newer:
                return cur
            cur = sorted(newer)[0]
            seen.add(cur)

    def direct_decisions(self, nid: str) -> list[str]:
        """Decisions linked to ``nid`` by any edge, in either direction (``decided_by``, ``pins``, ...)."""
        linked = {d for _, d in self.g.out_edges(nid)} | {s for s, _ in self.g.in_edges(nid)}
        return sorted(n for n in linked if self._is_decision(n))

    def decisions(self, nid: str) -> dict:
        """Decisions behind ``nid``: its own, those inherited from everything it relies on, and the specs it
        follows (a spec is the pre-registration, ADR 2026-07-15). Superseded decisions point to the current one.
        """
        if nid not in self.g:
            raise KeyError(nid)
        reliance = self._reliance()
        upstream = nx.descendants(reliance, nid)

        def entry(did: str, via: str | None = None) -> dict:
            cur = self.current_decision(did)
            out = {"id": did, "type": self._type(did), "status": self._status(did),
                   "title": self.g.nodes[did].get("title", "")}
            if cur != did:
                out["superseded_by"] = cur
            if store_of(self.g, did):
                out["store"] = store_of(self.g, did)
            if via:
                out["via"] = via
            return out

        direct = [entry(d) for d in self.direct_decisions(nid)]
        seen = {d["id"] for d in direct} | {nid}
        inherited = []
        for up in sorted(upstream):
            if self._is_decision(up):
                continue
            for d in self.direct_decisions(up):
                if d not in seen:
                    seen.add(d)
                    inherited.append(entry(d, via=up))
        specs = sorted(
            n for n in upstream | {nid} if self._type(n) == "Spec"
        )
        return {
            "node": nid,
            "direct": direct,
            "inherited": inherited,
            "specs": [{"id": s, "status": self._status(s), "anchor": self.g.nodes[s].get("anchor"),
                       **({"store": store_of(self.g, s)} if store_of(self.g, s) else {})}
                      for s in specs if s != nid],
        }

    # --- code layer ---

    def implemented_by(self, nid: str) -> list[str]:
        return sorted(d for _, d, a in self.g.out_edges(nid, data=True) if a.get("type") == "implemented_by")

    def code(self, nid: str) -> dict:
        """Code behind ``nid``: the CodeRefs it is implemented by, and those of everything it relies on (with the
        node they come through) — what to reread before trusting ``nid``."""
        if nid not in self.g:
            raise KeyError(nid)
        direct = self.implemented_by(nid)
        seen = set(direct)
        inherited = []
        for up in sorted(nx.descendants(self._reliance(), nid)):
            for c in self.implemented_by(up):
                if c not in seen:
                    seen.add(c)
                    inherited.append({"id": c, "via": up})
        return {"node": nid, "direct": direct, "inherited": inherited}
