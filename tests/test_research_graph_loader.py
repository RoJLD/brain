from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from research_graph.loader import ValidationError, load_store

STORE = Path(__file__).parent / "fixtures" / "research_graph"


def test_load_store_builds_graph():
    g = load_store(STORE)
    assert g.number_of_nodes() == 11
    assert g.number_of_edges() == 11
    assert g.nodes["exp001"]["type"] == "Experiment"
    assert g["exp002"]["v1"]["type"] == "gated_by"


def test_unknown_type_raises(tmp_path):
    (tmp_path / "nodes").mkdir()
    (tmp_path / "schema.yaml").write_text(
        "node_types: [Experiment]\nedge_types: [tests]\nstatuses: [open]\n",
        encoding="utf-8",
    )
    (tmp_path / "nodes" / "n.yaml").write_text(
        "- {id: x, type: Bogus, status: open, title: t}\n", encoding="utf-8"
    )
    (tmp_path / "edges.yaml").write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_store(tmp_path)
    assert any("unknown type" in e for e in exc.value.errors)


def test_dangling_edge_raises(tmp_path):
    (tmp_path / "nodes").mkdir()
    (tmp_path / "schema.yaml").write_text(
        "node_types: [Experiment]\nedge_types: [tests]\nstatuses: [open]\n",
        encoding="utf-8",
    )
    (tmp_path / "nodes" / "n.yaml").write_text(
        "- {id: a, type: Experiment, status: open, title: t}\n", encoding="utf-8"
    )
    (tmp_path / "edges.yaml").write_text("- {from: a, to: ghost, type: tests}\n", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_store(tmp_path)
    assert any("unknown target" in e for e in exc.value.errors)


def _schema_only(tmp_path):
    (tmp_path / "nodes").mkdir()
    (tmp_path / "schema.yaml").write_text(
        "node_types: [Experiment]\nedge_types: [tests]\nstatuses: [open]\n",
        encoding="utf-8",
    )
    (tmp_path / "edges.yaml").write_text("[]\n", encoding="utf-8")
    return tmp_path


def test_duplicate_id_raises(tmp_path):
    repo = _schema_only(tmp_path)
    (repo / "nodes" / "n.yaml").write_text(
        "- {id: a, type: Experiment, status: open, title: t}\n"
        "- {id: a, type: Experiment, status: open, title: t2}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as exc:
        load_store(repo)
    assert any("duplicate node id" in e for e in exc.value.errors)


def test_invalid_status_raises(tmp_path):
    repo = _schema_only(tmp_path)
    (repo / "nodes" / "n.yaml").write_text(
        "- {id: a, type: Experiment, status: bogus, title: t}\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError) as exc:
        load_store(repo)
    assert any("unknown status" in e for e in exc.value.errors)


def test_missing_id_raises(tmp_path):
    repo = _schema_only(tmp_path)
    (repo / "nodes" / "n.yaml").write_text(
        "- {type: Experiment, status: open, title: t}\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError) as exc:
        load_store(repo)
    assert any("without id" in e for e in exc.value.errors)


def test_missing_edges_file_raises_validation_error(tmp_path):
    (tmp_path / "nodes").mkdir()
    (tmp_path / "schema.yaml").write_text(
        "node_types: [Experiment]\nedge_types: [tests]\nstatuses: [open]\n",
        encoding="utf-8",
    )
    # no edges.yaml
    with pytest.raises(ValidationError) as exc:
        load_store(tmp_path)
    assert any("edges.yaml" in e for e in exc.value.errors)


def test_non_list_node_file_raises_validation_error(tmp_path):
    repo = _schema_only(tmp_path)
    (repo / "nodes" / "n.yaml").write_text("id: a\ntype: Experiment\n", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_store(repo)
    assert any("expected a YAML list" in e for e in exc.value.errors)


_SCHEMA_LVL = textwrap.dedent("""
    node_types: [Hypothesis]
    edge_types: [tests]
    statuses: [open]
    levels: [L0, L1, L2]
    """)


def _store_lvl(tmp_path, nodes_yaml):
    store = tmp_path / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "schema.yaml").write_text(_SCHEMA_LVL, encoding="utf-8")
    (store / "nodes" / "core.yaml").write_text(nodes_yaml, encoding="utf-8")
    (store / "edges.yaml").write_text("[]", encoding="utf-8")
    return store


def test_loader_captures_level(tmp_path):
    store = _store_lvl(tmp_path, "- {id: M1, type: Hypothesis, status: open, level: L1}")
    g = load_store(str(store))
    assert g.nodes["M1"]["level"] == "L1"


def test_loader_rejects_unknown_level(tmp_path):
    store = _store_lvl(tmp_path, "- {id: M1, type: Hypothesis, status: open, level: L9}")
    try:
        load_store(str(store))
        assert False, "expected ValidationError"
    except ValidationError as exc:
        assert any("unknown level" in e for e in exc.errors)
