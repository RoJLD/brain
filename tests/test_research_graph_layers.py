"""Layered graph (spec 2026-10-15-layered-graph-design): schema layers, per-type statuses, layer edge files,
work queries (frontier, blockers, milestone critical path), cross-layer impact, GitNexus export, CLI."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from research_graph.cli import main
from research_graph.export_gitnexus import build_payload
from research_graph.loader import ValidationError, load_store
from research_graph.model import LayeredGraph
from research_graph.schema import load_schema

STORE = Path(__file__).parent / "fixtures" / "layered_graph"


def _lg() -> LayeredGraph:
    return LayeredGraph(load_store(STORE))


def _copy_store(tmp_path: Path) -> Path:
    dst = tmp_path / "store"
    shutil.copytree(STORE, dst)
    return dst


# -- schema / loader -------------------------------------------------------------------------------


def test_schema_maps_types_to_layers_and_restricts_statuses():
    schema = load_schema(STORE / "schema.yaml")
    assert schema.layer_of("WorkItem") == "work" and schema.layer_of("Venue") == "data"
    assert schema.allowed_statuses("Milestone") == {"pending", "reached", "dropped"}
    assert schema.allowed_statuses("Experiment") == schema.statuses  # unrestricted type


def test_schema_rejects_unknown_layer_type(tmp_path):
    bad = tmp_path / "schema.yaml"
    bad.write_text("node_types: [A]\nedge_types: [e]\nstatuses: [s]\nlayers: {work: [B]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown node type"):
        load_schema(bad)


def test_status_not_allowed_for_type_is_rejected(tmp_path):
    store = _copy_store(tmp_path)
    (store / "nodes" / "bad.yaml").write_text(
        "- {id: wi-bad, type: WorkItem, status: validated, title: x}\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="not allowed for type 'WorkItem'"):
        load_store(store)


def test_layer_edge_files_are_loaded_and_nodes_tagged():
    g = load_store(STORE)
    assert g.has_edge("wi-b", "wi-a") and g.has_edge("ds-x", "tf-x")  # from edges/*.yaml
    assert g.has_edge("exp-x", "ds-x")  # from edges.yaml
    assert g.nodes["wi-a"]["layer"] == "work" and g.nodes["sa-x"]["layer"] == "risk"


def test_two_edges_on_one_node_pair_are_reported(tmp_path):
    store = _copy_store(tmp_path)
    (store / "edges" / "dup.yaml").write_text(
        "- {from: wi-b, to: wi-a, type: specified_by}\n", encoding="utf-8"
    )
    g = load_store(store)
    assert any("wi-b->wi-a" in c for c in g.graph["collapsed_edges"])


# -- work queries ----------------------------------------------------------------------------------


def test_work_frontier_needs_satisfied_prerequisites():
    # wi-a: done item + active spec -> startable. wi-d: draft spec -> not. wi-gated: open verdict -> not.
    assert _lg().work_frontier() == ["wi-a"]


def test_blocked_lists_blockers_and_external():
    blocked = _lg().blocked()
    assert blocked["wi-b"] == ["wi-a"]
    assert blocked["wi-d"] == ["spec-draft"]
    assert blocked["wi-gated"] == ["v-open"]
    assert blocked["wi-ext"] == ["external"]
    assert "wi-a" not in blocked and "wi-done" not in blocked


def test_milestone_progress_and_critical_path():
    m = _lg().milestone("ms-1")
    assert m["items"] == 4  # wi-c, wi-done directly + wi-a, wi-b through ms-sub
    assert m["by_status"] == {"done": 1, "todo": 3}
    assert m["critical_path"] == ["wi-a", "wi-b", "wi-c"]
    assert m["trigger"] == "t" and not m["cycle"]


# -- impact ----------------------------------------------------------------------------------------


def test_impact_crosses_layers():
    impact = _lg().impact("venue-x")
    assert impact["data"] == ["ad-x", "ds-x"]
    assert impact["research"] == ["edge-x", "exp-x"]
    assert "wi-done" not in sum(impact.values(), [])  # delivering the adapter is not relying on the venue


def test_impact_through_settlement_asset_and_transform():
    assert "edge-x" in _lg().impact("sa-x")["research"]
    assert _lg().impact("tf-x") == {"data": ["ds-x"], "research": ["edge-x", "exp-x"]}


def test_delivered_node_impacts_milestone():
    # The adapter relies on nothing in work, but a milestone relies on the item that delivers it.
    assert _lg().impact("wi-a")["work"] == ["ms-1", "ms-sub", "wi-b", "wi-c"]


# -- GitNexus export -------------------------------------------------------------------------------


def test_export_single_mode_works_with_the_current_sidecar():
    payload = build_payload(load_store(STORE))
    assert [d for d in payload["ddl"] if d.startswith("CREATE NODE TABLE")] == [
        "CREATE NODE TABLE Node(id STRING, type STRING, title STRING, status STRING, layer STRING, "
        "anchor STRING, level STRING, PRIMARY KEY(id))"
    ]
    assert "CREATE REL TABLE depends_on(FROM Node TO Node, id STRING)" in payload["ddl"]
    node = next(n for n in payload["nodes"] if n["props"]["id"] == "wi-a")
    assert node["table"] == "Node" and node["props"]["type"] == "WorkItem" and node["props"]["layer"] == "work"
    edge = next(e for e in payload["edges"] if e["from"] == "wi-b")
    assert edge == {"table": "depends_on", "from": "wi-b", "to": "wi-a", "props": {"id": "wi-b->depends_on->wi-a"}}


def test_export_typed_mode_tables_per_type():
    payload = build_payload(load_store(STORE), mode="typed")
    assert any(d.startswith("CREATE NODE TABLE WorkItem(id STRING") for d in payload["ddl"])
    rel = next(d for d in payload["ddl"] if d.startswith("CREATE REL TABLE depends_on("))
    assert "FROM WorkItem TO WorkItem" in rel and "FROM Adapter TO Venue" in rel
    assert rel.endswith(", id STRING)")  # the sidecar MERGEs relationships on `id`
    edge = next(e for e in payload["edges"] if e["from"] == "wi-b")
    assert (edge["from_table"], edge["to_table"]) == ("WorkItem", "WorkItem")
    with pytest.raises(ValueError):
        build_payload(load_store(STORE), mode="nested")


def test_export_payload_layer_filter():
    payload = build_payload(load_store(STORE), {"work"})
    assert {n["props"]["type"] for n in payload["nodes"]} == {"WorkItem", "Milestone", "Spec"}
    assert all(e["from"].startswith(("wi-", "ms-")) for e in payload["edges"])


# -- CLI -------------------------------------------------------------------------------------------


def test_cli_queries(capsys, tmp_path):
    store = str(STORE)
    assert main(["--store", store, "work-frontier"]) == 0
    assert capsys.readouterr().out.startswith("wi-a")
    assert main(["--store", store, "milestone", "ms-1"]) == 0
    assert "wi-a -> wi-b -> wi-c" in capsys.readouterr().out
    assert main(["--store", store, "impact", "nope"]) == 1
    out = tmp_path / "payload.json"
    assert main(["--store", store, "export-gitnexus", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["nodes"]


# -- decisions -------------------------------------------------------------------------------------


def test_decisions_direct_and_inherited_with_supersession():
    d = _lg().decisions("edge-x")
    assert [e["id"] for e in d["direct"]] == ["sdr-x"]
    inherited = {e["id"]: e for e in d["inherited"]}
    assert set(inherited) == {"adr-old"}
    assert inherited["adr-old"]["via"] == "ad-x"  # edge-x relies on ds-x, provided by ad-x
    assert inherited["adr-old"]["superseded_by"] == "adr-new"


def test_decisions_include_followed_specs():
    d = _lg().decisions("wi-b")  # wi-b relies on wi-a, which relies on spec-ok
    assert [s["id"] for s in d["specs"]] == ["spec-ok"]
    assert d["direct"] == [] and d["inherited"] == []


def test_current_decision_follows_supersedes_chain():
    lg = _lg()
    assert lg.current_decision("adr-old") == "adr-new"
    assert lg.current_decision("adr-new") == "adr-new"


def test_cli_decisions(capsys):
    assert main(["--store", str(STORE), "decisions", "edge-x"]) == 0
    out = capsys.readouterr().out
    assert "sdr-x" in out and "superseded by adr-new" in out and "(via ad-x)" in out


# -- overlay (a sibling repo's store, e.g. ops-repo ops/graph) -----------------------------------


def _overlay(tmp_path, nodes, edges, external, anchor_file=True):
    repo = tmp_path / "fund"
    store = repo / "ops" / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "edges").mkdir()
    (store / "schema.yaml").write_text(
        "node_types: [Deployment, Stage]\nedge_types: [deploys, part_of, runs_on]\nstatuses: [active, planned]\n"
        "layers: {operations: [Deployment, Stage]}\nstatus_by_type: {Stage: [active, planned]}\n", encoding="utf-8")
    (store / "nodes" / "n.yaml").write_text(nodes, encoding="utf-8")
    (store / "edges" / "e.yaml").write_text(edges, encoding="utf-8")
    (store / "external.yaml").write_text(external, encoding="utf-8")
    if anchor_file:
        (repo / "cfg.yaml").write_text("x: 1\n", encoding="utf-8")
    return store


GOOD_NODES = ("- {id: dep-1, type: Deployment, status: active, title: d}\n"
              "- {id: st-1, type: Stage, status: active, title: s, anchor: 'cfg.yaml#top'}\n")
GOOD_EDGES = ("- {from: dep-1, to: edge-x, type: deploys}\n- {from: st-1, to: dep-1, type: part_of}\n"
              "- {from: st-1, to: venue-x, type: runs_on}\n")
GOOD_EXT = "- {id: edge-x}\n- {id: venue-x}\n"


def test_overlay_adds_an_operations_layer_and_crosses_impact(tmp_path):
    from research_graph.loader import apply_overlay

    g = load_store(STORE)
    apply_overlay(g, _overlay(tmp_path, GOOD_NODES, GOOD_EDGES, GOOD_EXT), tmp_path)
    lg = LayeredGraph(g)
    assert lg.layer("operations") == ["dep-1", "st-1"]
    assert lg.impact("venue-x")["operations"] == ["dep-1", "st-1"]  # the stage runs on the venue
    # The deployment relies on the edge it deploys (which relies on ds-x); a stage is a part OF the deployment,
    # so it is reached only through its own dependencies (harness, datasets), like work items and milestones.
    assert lg.impact("ds-x")["operations"] == ["dep-1"]
    assert g.nodes["st-1"]["anchor"] == "fund/cfg.yaml#top"  # rewritten relative to the repo root


def test_overlay_rejects_missing_externals_clashes_and_bad_status(tmp_path):
    from research_graph.loader import apply_overlay

    bad_nodes = GOOD_NODES + "- {id: wi-a, type: Stage, status: active, title: clash}\n" \
                             "- {id: st-2, type: Stage, status: done, title: bad status}\n"
    store = _overlay(tmp_path, bad_nodes, GOOD_EDGES + "- {from: st-1, to: nowhere, type: runs_on}\n",
                     GOOD_EXT + "- {id: not-in-graph}\n")
    with pytest.raises(ValidationError) as info:
        apply_overlay(load_store(STORE), store, tmp_path)
    errors = "\n".join(info.value.errors)
    assert "wi-a: id already used" in errors and "st-2: status 'done' not allowed" in errors
    assert "'not-in-graph' does not exist" in errors and "st-1->nowhere: unknown endpoint" in errors


def test_cli_overlay(tmp_path, capsys):
    store = _overlay(tmp_path, GOOD_NODES, GOOD_EDGES, GOOD_EXT)
    assert main(["--store", str(STORE), "--repo-root", str(tmp_path), "--overlay", str(store), "layer", "operations"]) == 0
    assert "dep-1" in capsys.readouterr().out


def test_overlay_on_another_drive_keeps_absolute_anchors(tmp_path, monkeypatch):
    from research_graph import loader

    def no_common_drive(*args, **kwargs):
        raise ValueError("path is on mount 'C:', start on mount 'E:'")

    monkeypatch.setattr(loader.os.path, "relpath", no_common_drive)
    g = load_store(STORE)
    loader.apply_overlay(g, _overlay(tmp_path, GOOD_NODES, GOOD_EDGES, GOOD_EXT), tmp_path)
    assert g.nodes["st-1"]["anchor"].endswith("fund/cfg.yaml#top")
    assert Path(g.nodes["st-1"]["anchor"].split("#")[0]).is_absolute()
