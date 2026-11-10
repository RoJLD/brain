from __future__ import annotations

from pathlib import Path

import networkx as nx

from research_graph.loader import load_store, read_foreign
from research_graph.model import LayeredGraph, ResearchGraph, kind, label, store_of
from research_graph.model import ResearchGraph as _RG
from tests.two_stores import two_stores

STORE = Path(__file__).parent / "fixtures" / "research_graph"


def _rg() -> ResearchGraph:
    return ResearchGraph(load_store(STORE))


def test_frontier_lists_runnable_experiments():
    # exp002 is planned and its only gate (v1) is validated -> runnable.
    # exp003 is planned but gate v2 is open -> not runnable.
    assert _rg().frontier() == ["exp002"]


def test_gated_lists_blocked_experiments():
    assert _rg().gated() == ["exp003"]


def test_provenance_returns_reasoning_cluster():
    prov = set(_rg().provenance("v1"))
    assert {"exp001", "sdr-a", "H1", "paper-x"} <= prov
    assert "exp003" not in prov  # disconnected cluster


def test_supersedes_chain():
    assert _rg().supersedes_chain("sdr-c") == ["sdr-c", "sdr-a"]


def test_gate_to_non_verdict_does_not_make_runnable():
    g = nx.DiGraph()
    g.add_node("expX", type="Experiment", status="planned")
    g.add_node("expY", type="Experiment", status="validated")  # not a Verdict
    g.add_edge("expX", "expY", type="gated_by")
    rg = _RG(g)
    assert rg.frontier() == []  # gated by a non-Verdict -> NOT runnable
    assert rg.gated() == ["expX"]


def test_supersedes_chain_terminates_on_cycle():
    g = nx.DiGraph()
    g.add_node("a", type="SDR", status="active")
    g.add_node("b", type="SDR", status="active")
    g.add_edge("a", "b", type="supersedes")
    g.add_edge("b", "a", type="supersedes")
    rg = _RG(g)
    chain = rg.supersedes_chain("a")
    assert chain == ["a", "b"]  # stops when it revisits 'a'


def test_another_stores_node_counts_where_it_is_linked_and_is_listed_nowhere(tmp_path):
    """wi-brain-cross-store-edges: another store's item counts in a milestone's progress and its blocker blocks,
    its ADR is a decision behind a node, its milestone is a sub-milestone (not an item); no listing holds it."""
    home, parent = two_stores(tmp_path)
    lg = LayeredGraph(load_store(parent, foreign=read_foreign([("home:graph", home)])))
    assert lg.milestone_items("ms-parent") == ["wi-a", "wi-s"] and lg.milestone("ms-parent")["items"] == 2
    assert lg.decisions("wi-s")["direct"] == [
        {"id": "adr-x", "type": "ADR", "status": "active", "title": "A decision", "store": "home:graph"}]
    assert lg.work_frontier() == ["wi-s"] and "wi-a" not in lg.layer("work") and "ms-home" not in lg.layer("work")
    assert lg.impact("adr-x") == {"work": ["ms-parent", "wi-s"]}
    assert (kind(lg.g, "ms-home"), store_of(lg.g, "ms-home"), label(lg.g, "ms-home")) == (
        "Milestone", "home:graph", "ms-home (home:graph)")
    lg = LayeredGraph(load_store(home, foreign=read_foreign([("parent:graph", parent)])))
    assert lg.blockers("wi-a") == ["wi-s"] and lg.blocked() == {"wi-a": ["wi-s"]}
    assert lg.impact("wi-b") == {"store parent:graph": ["ms-parent"]}   # parent's milestone relies on home's item
    assert (label(lg.g, "wi-a"), store_of(lg.g, "wi-a")) == ("wi-a", None)
