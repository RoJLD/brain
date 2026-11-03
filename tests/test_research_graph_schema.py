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


def test_required_props_are_read_and_checked(tmp_path):
    p = tmp_path / "schema.yaml"
    p.write_text("node_types: [Lesson, WorkItem]\nedge_types: [led_to]\nstatuses: [open, todo]\n"
                 "required_props:\n  Lesson: [trigger, anti_pattern, check]\n", encoding="utf-8")
    s = load_schema(p)
    assert s.required_props == {"Lesson": ("trigger", "anti_pattern", "check")}
    assert s.missing_props("Lesson", {"trigger": "t", "anti_pattern": "", "check": "c"}) == ["anti_pattern"]
    assert s.missing_props("Lesson", None) == ["trigger", "anti_pattern", "check"]
    assert s.missing_props("WorkItem", {}) == []


def test_required_props_refuse_an_unknown_type_or_a_bad_list(tmp_path):
    p = tmp_path / "schema.yaml"
    p.write_text("node_types: [A]\nedge_types: [x]\nstatuses: [open]\nrequired_props:\n  B: [k]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown node type 'B'"):
        load_schema(p)
    p.write_text("node_types: [A]\nedge_types: [x]\nstatuses: [open]\nrequired_props:\n  A: k\n", encoding="utf-8")
    with pytest.raises(ValueError, match="list of prop names"):
        load_schema(p)


def test_the_store_template_has_the_lesson_type(tmp_path):
    text = (Path(__file__).parents[1] / "src" / "research_graph" / "templates" / "schema.yaml").read_text(
        encoding="utf-8").replace("{owner_line}", "")
    p = tmp_path / "schema.yaml"
    p.write_text(text, encoding="utf-8")
    s = load_schema(p)
    assert "Lesson" in s.node_types and {"learned_from", "enforced_by", "led_to"} <= s.edge_types
    assert s.layer_of("Lesson") == "lessons" and s.allowed_statuses("Lesson") >= {"open", "enforced", "regressed"}
    assert s.required_props["Lesson"] == ("trigger", "anti_pattern", "check")
