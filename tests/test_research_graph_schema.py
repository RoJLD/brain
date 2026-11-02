from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from research_graph.schema import load_schema

FIXTURE = Path(__file__).parent / "fixtures" / "research_graph" / "schema.yaml"


def test_package_imports():
    import research_graph  # noqa: F401


def test_load_schema_reads_vocabulary():
    schema = load_schema(FIXTURE)
    assert "Experiment" in schema.node_types
    assert "gated_by" in schema.edge_types
    assert "validated" in schema.statuses
    assert len(schema.node_types) == 6


def test_load_schema_missing_key_raises(tmp_path):
    bad = tmp_path / "schema.yaml"
    bad.write_text("node_types: [A]\nedge_types: [x]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="statuses"):
        load_schema(bad)


def test_load_schema_reads_levels(tmp_path):
    p = tmp_path / "schema.yaml"
    p.write_text(
        textwrap.dedent("""
        node_types: [Hypothesis]
        edge_types: [instantiates]
        statuses: [proposed]
        levels: [L0, L1, L2]
        """),
        encoding="utf-8",
    )
    s = load_schema(p)
    assert s.levels == frozenset({"L0", "L1", "L2"})


def test_load_schema_levels_defaults_empty(tmp_path):
    p = tmp_path / "schema.yaml"
    p.write_text(
        textwrap.dedent("""
        node_types: [Hypothesis]
        edge_types: [tests]
        statuses: [open]
        """),
        encoding="utf-8",
    )
    s = load_schema(p)
    assert s.levels == frozenset()


def test_load_schema_reads_the_owner(tmp_path):
    """Who decides for the store: the loaded graph carries it, ``pending`` lists the items blocked on them."""
    from research_graph.loader import load_store

    assert load_schema(FIXTURE).owner is None
    store = tmp_path / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "schema.yaml").write_text("owner: Ada\nnode_types: [A]\nedge_types: [x]\nstatuses: [s]\n",
                                       encoding="utf-8")
    (store / "edges.yaml").write_text("[]\n", encoding="utf-8")
    assert load_schema(store / "schema.yaml").owner == "Ada"
    assert load_store(store).graph["owner"] == "Ada"
