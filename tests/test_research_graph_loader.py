from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from research_graph.loader import ValidationError, load_store, read_foreign
from research_graph.model import FOREIGN
from tests.two_stores import two_stores

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


def test_a_node_missing_a_required_prop_is_an_error(tmp_path):
    (tmp_path / "nodes").mkdir()
    (tmp_path / "schema.yaml").write_text(
        "node_types: [Lesson]\nedge_types: [led_to]\nstatuses: [open]\nrequired_props:\n  Lesson: [trigger, check]\n",
        encoding="utf-8",
    )
    (tmp_path / "nodes" / "lessons.yaml").write_text(
        "- {id: les-a, type: Lesson, status: open, title: t, props: {trigger: x, check: y}}\n"
        "- {id: les-b, type: Lesson, status: open, title: t, props: {trigger: x, check: \"\"}}\n", encoding="utf-8"
    )
    (tmp_path / "edges.yaml").write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_store(tmp_path)
    assert exc.value.errors == ["node les-b: Lesson needs props check"]


# --- edges to another store's node (wi-brain-cross-store-edges) ---


def test_an_edge_to_another_stores_id_is_refused_without_foreign_as_before(tmp_path):
    home, _ = two_stores(tmp_path)
    with pytest.raises(ValidationError) as exc:
        load_store(home)
    assert exc.value.errors == ["edge wi-a->wi-s: unknown target 'wi-s'",
                                "edge wi-b->ms-parent: unknown target 'ms-parent'"]


def test_foreign_ids_load_the_edge_and_the_node_is_named_by_its_store(tmp_path):
    home, parent = two_stores(tmp_path)
    g = load_store(home, foreign=read_foreign([("parent:graph", parent)]))
    s = g.nodes["wi-s"]
    assert (s["type"], s["foreign_type"], s[FOREIGN], s["status"], s["title"]) == (
        None, "WorkItem", "parent:graph", "todo", "Parent step")
    assert g["wi-a"]["wi-s"]["type"] == "depends_on" and g["wi-b"]["ms-parent"]["type"] == "part_of"
    assert "ms-parent" in g and g.nodes["ms-home"].get(FOREIGN) is None   # the store's own node stays its own
    assert sorted(n for n, a in g.nodes(data=True) if a.get("type") == "WorkItem") == ["wi-a", "wi-b"]


def test_a_dangling_edge_is_still_refused_with_foreign_ids(tmp_path):
    home, parent = two_stores(tmp_path)
    with (home / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write("- {from: wi-a, to: wi-ghost, type: depends_on}\n- {from: wi-s, to: ms-parent, type: part_of}\n")
    with pytest.raises(ValidationError) as exc:
        load_store(home, foreign=read_foreign([("parent", parent)]))
    assert exc.value.errors == [
        "edge wi-a->wi-ghost: unknown target 'wi-ghost'",
        "edge wi-s->ms-parent: both ends are other stores' nodes (an edge belongs to the store of one)"]


def test_a_bare_label_is_enough_and_the_stores_own_id_wins(tmp_path):
    home, _ = two_stores(tmp_path)
    g = load_store(home, foreign={"wi-s": "parent", "ms-parent": "parent", "wi-a": "elsewhere"})
    assert g.nodes["wi-s"][FOREIGN] == "parent" and g.nodes["wi-s"]["foreign_type"] is None
    assert g.nodes["wi-a"]["type"] == "WorkItem" and FOREIGN not in g.nodes["wi-a"]


def test_read_foreign_skips_what_does_not_parse_and_keeps_the_first_store(tmp_path):
    home, parent = two_stores(tmp_path)
    (parent / "nodes" / "broken.yaml").write_text("- {id: [unclosed\n", encoding="utf-8")
    ids = read_foreign([("parent", parent), ("home", home), ("gone", tmp_path / "nowhere")])
    assert ids["wi-s"] == {"store": "parent", "type": "WorkItem", "title": "Parent step", "status": "todo"}
    assert ids["wi-a"]["store"] == "home" and set(ids) == {"wi-s", "ms-parent", "wi-a", "wi-b", "ms-home", "adr-x"}
