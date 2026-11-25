"""wi-brain-organ-placement (brain.placement): every node's organ, the module of the registry it serves, by hand
(props.module) or derived from the modules of its neighbours placed by hand, one hop along the edges that say what a
node belongs to, with its votes; the module view's placement section, brain modules --json's placement, and the organ
line of brain item show and brain features show. No persisted format: computed when read."""

import json

import networkx as nx

from brain import cli, modules, placement

REGISTRY = """\
- {id: P2, name: kettle-core, brick: P, phase: MVP, status: tree}
- {id: K1, name: tea-room, brick: K, phase: MVP, status: tree}
- {id: M4, name: lamp-post, brick: M, phase: V1, status: proposed, since: 2026-08-01}
"""
SCHEMA = """\
node_types: [WorkItem, Feature, Doc, Test, CodeRef, ADR, Milestone, Spec, Rule, Hook, DDR]
edge_types: [documented_in, implemented_by, tested_by, specified_by, decided_by, enforced_by, delivers, learned_from,
  led_to, part_of, about, depends_on]
statuses: [active, todo, have, planned, pending, archived]
"""
NODES = """\
- {id: wi-a, type: WorkItem, status: todo, title: "A", props: {module: P2}}
- {id: wi-b, type: WorkItem, status: todo, title: "B", props: {module: P2}}
- {id: wi-c, type: WorkItem, status: todo, title: "C", props: {module: K1}}
- {id: wi-out, type: WorkItem, status: todo, title: "Out", props: {module: none, module_reason: "the brain's own"}}
- {id: wi-odd, type: WorkItem, status: todo, title: "Odd", props: {module: Z9}}
- {id: feat-a, type: Feature, status: have, title: "Feature A", props: {domain: d, repo: lab, module: K1}}
- {id: feat-b, type: Feature, status: planned, title: "Feature B", props: {domain: d, repo: lab}}
- {id: doc-1, type: Doc, status: active, title: "Doc one"}
- {id: doc-2, type: Doc, status: active, title: "Doc two"}
- {id: test-1, type: Test, status: active, title: "Test one"}
- {id: code-1, type: CodeRef, status: active, title: "src/x.py"}
- {id: adr-1, type: ADR, status: active, title: "ADR one"}
- {id: ms-1, type: Milestone, status: pending, title: "Milestone one"}
- {id: spec-1, type: Spec, status: active, title: "Spec one"}
- {id: rule-1, type: Rule, status: active, title: "Rule one"}
- {id: hook-1, type: Hook, status: active, title: "Hook one", props: {module: M4}}
- {id: ddr-1, type: DDR, status: archived, title: "DDR one"}
"""
EDGES = """\
- {from: wi-a, to: doc-1, type: documented_in}
- {from: wi-b, to: doc-1, type: documented_in}
- {from: wi-c, to: doc-1, type: documented_in}
- {from: wi-a, to: doc-2, type: documented_in}
- {from: wi-c, to: doc-2, type: documented_in}
- {from: wi-a, to: test-1, type: tested_by}
- {from: wi-c, to: test-1, type: tested_by}
- {from: feat-a, to: test-1, type: tested_by}
- {from: feat-a, to: code-1, type: implemented_by}
- {from: wi-odd, to: code-1, type: implemented_by}
- {from: wi-out, to: code-1, type: implemented_by}
- {from: wi-a, to: adr-1, type: decided_by}
- {from: wi-a, to: ms-1, type: part_of}
- {from: wi-b, to: ms-1, type: part_of}
- {from: wi-c, to: ms-1, type: part_of}
- {from: spec-1, to: doc-1, type: documented_in}
- {from: rule-1, to: hook-1, type: enforced_by}
- {from: wi-a, to: feat-a, type: delivers}
- {from: wi-b, to: feat-a, type: delivers}
- {from: wi-a, to: wi-out, type: led_to}
- {from: wi-a, to: wi-odd, type: led_to}
- {from: ddr-1, to: wi-a, type: about}
- {from: wi-b, to: wi-c, type: depends_on}
"""
KNOWN = {"P2", "K1", "M4"}


def _store(tmp_path, registry=REGISTRY):
    s = tmp_path / "lab" / "notes" / "graph"
    (s / "nodes").mkdir(parents=True)
    (s / "edges").mkdir()
    (s / "schema.yaml").write_text(SCHEMA, encoding="utf-8")
    (s / "edges.yaml").write_text("", encoding="utf-8")
    (s / "nodes" / "work.yaml").write_text(NODES, encoding="utf-8")
    (s / "edges" / "work.yaml").write_text(EDGES, encoding="utf-8")
    if registry is not None:
        (s / "modules.yaml").write_text(registry, encoding="utf-8")
    return s


def _graph(tmp_path):
    g = placement.load(_store(tmp_path))
    assert g is not None
    return g


def _place(tmp_path):
    return placement.place_all(_graph(tmp_path), KNOWN)


# --- the rule ---

def test_a_clear_majority_places_a_node_and_its_votes_are_its_evidence(tmp_path):
    got = _place(tmp_path)
    doc = got["doc-1"]   # P2 2, K1 1: exactly twice is a clear majority
    assert (doc.state, doc.organ, doc.hand) == ("derived", "P2", "")
    assert doc.votes == {"P2": {"documented_in": 2}, "K1": {"documented_in": 1}}
    assert doc.tally() == [("P2", 2), ("K1", 1)] and doc.total() == 3
    assert doc.weights() == {"P2": 0.67, "K1": 0.33}   # a distribution, the most voted first
    assert (got["test-1"].state, got["test-1"].organ) == ("derived", "K1")   # a feature votes as an item does
    assert (got["ms-1"].state, got["ms-1"].organ) == ("derived", "P2")       # part_of, read towards its target
    assert (got["adr-1"].state, got["adr-1"].organ) == ("derived", "P2")     # a single vote is a clear majority
    assert (got["rule-1"].state, got["rule-1"].organ) == ("derived", "M4")   # a hook placed by hand places its rule


def test_a_split_vote_and_no_vote_leave_a_node_without_an_organ(tmp_path):
    got = _place(tmp_path)
    assert (got["doc-2"].state, got["doc-2"].organ) == ("split", "")   # P2 1, K1 1
    assert got["doc-2"].votes == {"P2": {"documented_in": 1}, "K1": {"documented_in": 1}}
    assert (got["feat-b"].state, got["feat-b"].votes) == ("unplaced", {})
    assert got["ddr-1"].state == "unplaced"   # about is not an edge that places: the records need a second hop


def test_the_clear_majority_threshold():
    assert placement.clear([("P2", 3), ("K1", 2)]) == ""     # 1.5 times: split
    assert placement.clear([("P2", 4), ("K1", 2)]) == "P2"   # twice
    assert placement.clear([("P2", 1)]) == "P2" and placement.clear([]) == ""


def test_only_hand_placements_vote_one_hop_away(tmp_path):
    got = _place(tmp_path)
    assert got["spec-1"].state == "unplaced"   # its only neighbour, doc-1, is derived: no vote, no order effect
    assert got["code-1"].votes == {"K1": {"implemented_by": 1}}   # none and an unknown module give no vote
    assert got["wi-c"].votes == {}   # depends_on from wi-b (P2) is not an edge that places


def test_a_hand_placement_overrides_and_is_contradicted_by_a_clear_majority(tmp_path):
    got = _place(tmp_path)
    feat = got["feat-a"]   # K1 by hand; wi-a and wi-b (P2) deliver it
    assert (feat.state, feat.organ, feat.hand) == ("contradicted", "K1", "K1")
    assert feat.votes == {"P2": {"delivers": 2}}
    assert (got["wi-a"].state, got["wi-a"].votes) == ("hand", {"K1": {"delivers": 1}})   # one link never contradicts
    assert (got["wi-c"].state, got["wi-c"].organ) == ("hand", "K1")   # no vote: no gap
    assert (got["wi-out"].state, got["wi-out"].organ) == ("hand", "none")   # outside the tree: never contradicted
    assert (got["wi-odd"].state, got["wi-odd"].organ) == ("hand", "Z9")   # unknown: brain check's, not a contradiction
    assert (got["hook-1"].state, got["hook-1"].organ) == ("hand", "M4")


def test_another_stores_node_is_never_placed_and_an_edge_in_both_directions_votes():
    g = nx.DiGraph()
    g.add_node("wi-x", type="WorkItem", props={"module": "P2"})
    g.add_node("doc-x", type="Doc")
    g.add_node("wi-far", foreign="other:notes/graph", props={"module": "K1"})
    g.add_edge("doc-x", "wi-x", type="documented_in")   # the reverse direction counts too
    g.add_edge("wi-far", "doc-x", type="documented_in")
    assert placement.own_nodes(g) == ["doc-x", "wi-x"]
    p = placement.place(g, "doc-x", KNOWN)
    assert (p.state, p.organ) == ("derived", "P2") and "K1" not in p.votes   # another registry's module: no vote


def test_counts_by_type_and_the_json(tmp_path):
    g = _graph(tmp_path)
    rows = placement.by_type(placement.place_all(g, KNOWN))
    assert rows["Doc"] == {"nodes": 2, "hand": 0, "contradicted": 0, "derived": 1, "split": 1, "unplaced": 0}
    assert rows["Feature"] == {"nodes": 2, "hand": 0, "contradicted": 1, "derived": 0, "split": 0, "unplaced": 1}
    assert (rows["WorkItem"]["hand"], rows["WorkItem"]["contradicted"]) == (5, 0)
    d = placement.data(g, KNOWN)
    assert (d["majority"], d["contradict"]) == (2, 2) and d["edges"][0] == "documented_in" and len(d["edges"]) == 10
    assert [c["node"] for c in d["contradicted"]] == ["feat-a"]
    assert d["contradicted"][0]["weights"] == {"P2": 1.0}
    assert json.dumps(d)   # plain data


# --- the lines ---

def test_the_organ_line_of_each_state(tmp_path):
    got, names = _place(tmp_path), {"P2": "kettle-core", "K1": "tea-room", "M4": "lamp-post"}
    assert placement.line(got["doc-1"], names) == \
        "organ: P2 kettle-core, derived from 2 of 3 link(s) (P2 2: documented_in 2; K1 1: documented_in 1)"
    assert placement.line(got["doc-2"], names) == \
        "organ: split, no clear majority (K1 1: documented_in 1; P2 1: documented_in 1); props.module places it"
    assert placement.line(got["feat-b"]) == \
        "organ: unplaced (no link to a node placed by hand); props.module places it"
    assert placement.line(got["feat-a"], names) == ("organ: K1 tea-room, by hand (props.module); contradicted: its "
                                                    "links give P2 a clear majority (2 of 2: P2 2: delivers 2)")
    assert placement.line(got["hook-1"], names) == "organ: M4 lamp-post, by hand (props.module)"
    assert placement.line(got["wi-out"], names).startswith("organ: none, by hand (outside the tree); its links: P2 1")
    assert placement.line(got["wi-odd"]) == "organ: Z9, by hand (props.module); its links: P2 1: led_to 1"


def test_the_view_section_counts_by_type_and_lists_the_contradicted(tmp_path):
    store = _store(tmp_path)
    text = modules.render(store, "notes/graph", tmp_path / "lab")
    assert "\n## Placement\n" in text and text.index("## Placement") < text.index("\n## P2\n")
    assert "| Doc | 2 | 0 | 1 | 1 | 0 | 0 |" in text
    assert "| Feature | 2 | 1 | 0 | 0 | 1 | 1 |" in text   # by hand counts the contradicted one
    assert "| **All** | 17 |" in text
    assert "- `feat-a` (Feature): K1 tea-room by hand, its links P2 2: delivers 2" in text
    assert modules.render(store, "notes/graph", tmp_path / "lab") == text   # no date: the same store, the same view
    d = modules.data(store, tmp_path / "lab")
    assert d["placement"]["by_type"]["Doc"]["derived"] == 1


def test_a_store_whose_graph_does_not_load_gets_one_line(tmp_path):
    store = _store(tmp_path)
    (store / "edges.yaml").unlink()   # research_graph refuses a store without it
    assert placement.load(store) is None
    text = modules.render(store, "notes/graph", tmp_path / "lab")
    assert "## Placement\n\nNot derived: the store's graph does not load (brain check says why)." in text
    assert modules.data(store, tmp_path / "lab")["placement"] is None


# --- brain item show, brain features show ---

def _cli(tmp_path, monkeypatch, registry=REGISTRY):
    store = _store(tmp_path, registry)
    root = store.parents[1]
    (tmp_path / "projects.yaml").write_text(f"lab:\n  root: {root.as_posix()}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "projects.yaml"))
    return root


def test_item_show_prints_the_organ_line_and_its_json(tmp_path, monkeypatch, capsys):
    root = _cli(tmp_path, monkeypatch)
    assert cli.main(["--project", "lab", "--root", str(root), "item", "show", "doc-1"]) == 0
    out = capsys.readouterr().out
    assert "\n  organ: P2 kettle-core, derived from 2 of 3 link(s)" in out
    assert cli.main(["--project", "lab", "--root", str(root), "item", "show", "feat-a", "--json"]) == 0
    organ = json.loads(capsys.readouterr().out)["organ"]
    assert organ["state"] == "contradicted" and organ["votes"] == {"P2": {"delivers": 2}}


def test_item_show_without_a_registry_has_no_organ_line(tmp_path, monkeypatch, capsys):
    root = _cli(tmp_path, monkeypatch, registry=None)
    assert cli.main(["--project", "lab", "--root", str(root), "item", "show", "doc-1"]) == 0
    assert "organ:" not in capsys.readouterr().out
    assert cli.main(["--project", "lab", "--root", str(root), "item", "show", "doc-1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["organ"] is None


def test_features_show_prints_the_organ_line_and_its_json(tmp_path, monkeypatch, capsys):
    root = _cli(tmp_path, monkeypatch)
    base = ["--project", "lab", "--root", str(root), "features", "show"]
    assert cli.main(base + ["feat-a"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[2] == ("  organ: K1 tea-room, by hand (props.module); contradicted: its links give P2 a clear "
                        "majority (2 of 2: P2 2: delivers 2)")   # under the domain line
    assert cli.main(base + ["feat-b", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["organ"]["state"] == "unplaced"
