"""GitNexus export of the code layer (spec 2026-10-17-graph-code-layer-design §3.7): tables holding CodeRef nodes
get repo / path / symbol columns parsed from the id; the DDL is unchanged without the code layer. The other export
tests (single / typed modes, layer filter) are in test_research_graph_layers.py."""

from __future__ import annotations

from pathlib import Path

from research_graph.export_gitnexus import build_payload
from research_graph.loader import load_store

STORE = Path(__file__).parent / "fixtures" / "code_layer"


def test_export_carries_repo_path_symbol_for_code_refs():
    g = load_store(STORE)
    payload = build_payload(g)
    node_ddl = [d for d in payload["ddl"] if d.startswith("CREATE NODE TABLE")]
    assert node_ddl == [
        "CREATE NODE TABLE Node(id STRING, type STRING, title STRING, status STRING, layer STRING, "
        "anchor STRING, level STRING, repo STRING, path STRING, symbol STRING, PRIMARY KEY(id))"
    ]
    props = {n["props"]["id"]: n["props"] for n in payload["nodes"]}
    method = props["code:fake-repo:fake_pkg/venue.py::FakeVenue.funding"]
    assert (method["repo"], method["path"], method["symbol"]) == (
        "fake-repo",
        "fake_pkg/venue.py",
        "FakeVenue.funding",
    )
    assert props["code:fake-repo:fake_pkg/store.py"]["symbol"] == ""
    assert (props["ad-x"]["repo"], props["ad-x"]["path"]) == ("", "")
    assert "CREATE REL TABLE implemented_by(FROM Node TO Node, id STRING)" in payload["ddl"]


def test_export_typed_mode_adds_code_columns_to_the_coderef_table_only():
    payload = build_payload(load_store(STORE), mode="typed")
    code_ddl = next(d for d in payload["ddl"] if d.startswith("CREATE NODE TABLE CodeRef("))
    assert code_ddl.endswith("repo STRING, path STRING, symbol STRING, PRIMARY KEY(id))")
    adapter_ddl = next(d for d in payload["ddl"] if d.startswith("CREATE NODE TABLE Adapter("))
    assert "repo STRING" not in adapter_ddl
    assert "FROM Adapter TO CodeRef" in next(
        d for d in payload["ddl"] if "REL TABLE implemented_by" in d
    )


def test_export_without_the_code_layer_keeps_the_ddl_unchanged():
    payload = build_payload(load_store(STORE), {"data", "research"})
    assert "repo STRING" not in payload["ddl"][0]
    assert all("repo" not in n["props"] for n in payload["nodes"])
