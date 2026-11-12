"""wi-brain-item-size: props.size and props.size_reason given by the session that writes an item, and brain check's
warning on an open item written since the rule without one."""

from datetime import date

import pytest
import yaml

from brain import cli, graph, sizing


def _nodes(store):
    return {n["id"]: n for n in yaml.safe_load((store / "nodes" / "work.yaml").read_text(encoding="utf-8"))}


def test_item_add_takes_a_size_and_stamps_created(store, capsys):
    root = store.parents[1]
    assert cli.main(["--root", str(root), "item", "add", "wi-sized", "--title", "Sized", "--size", "m",
                     "--size-reason", "one option and its test"]) == 0
    out = capsys.readouterr().out
    assert "size: none" not in out
    props = _nodes(store)["wi-sized"]["props"]
    assert props == {"size": "M", "size_reason": "one option and its test", "created": date.today().isoformat()}
    assert cli.main(["--root", str(root), "item", "add", "wi-bare", "--title", "Bare"]) == 0
    assert "size: none; give one (brain item set wi-bare size=S|M|L|XL size_reason=...)" in capsys.readouterr().out
    assert _nodes(store)["wi-bare"]["props"] == {"created": date.today().isoformat()}


def test_item_add_refuses_a_size_without_its_reason_or_off_the_scale(store, capsys):
    root = store.parents[1]
    assert cli.main(["--root", str(root), "item", "add", "wi-x", "--title", "X", "--size", "M"]) == 1
    assert "--size needs its --size-reason" in capsys.readouterr().err
    assert cli.main(["--root", str(root), "item", "add", "wi-x", "--title", "X", "--size-reason", "why"]) == 1
    with pytest.raises(SystemExit):
        cli.main(["--root", str(root), "item", "add", "wi-x", "--title", "X", "--size", "XXL", "--size-reason", "w"])
    assert "wi-x" not in _nodes(store)


def test_a_milestone_is_not_stamped(store):
    root = store.parents[1]
    assert cli.main(["--root", str(root), "item", "add", "ms-y", "--title", "Y", "--type", "Milestone",
                     "--status", "pending"]) == 0
    assert "props" not in _nodes(store)["ms-y"]


def test_set_sizes_an_item_in_any_case_and_refuses_off_the_scale(store):
    graph.set_item(store, "wi-one", ["size=xl", "size_reason=three modules and a format"])
    assert _nodes(store)["wi-one"]["props"]["size"] == "XL"
    with pytest.raises(graph.GraphError, match="size 'H' is not one of S, M, L, XL"):
        graph.set_item(store, "wi-one", ["props.size=h"])
    with pytest.raises(graph.GraphError, match="is not one of"):
        graph.add_item(store, "wi-new", "x", props={"size": "medium"})
    graph.set_item(store, "wi-one", ["size=", "size_reason="])   # an empty value removes it
    assert "size" not in _nodes(store)["wi-one"]["props"]


def test_check_warns_on_an_item_written_since_the_rule_without_a_size(store, monkeypatch, capsys):
    root = store.parents[1]
    monkeypatch.setattr(graph, "research_graph", lambda *a: 0)
    assert cli.main(["--root", str(root), "check"]) == 0
    assert "size" not in capsys.readouterr().out   # wi-one and wi-two predate the rule: no created stamp
    graph.add_item(store, "wi-new", "New", props={"created": "2026-11-12"})
    graph.add_item(store, "wi-done", "Done", status="done", props={"created": "2026-11-12"})
    graph.set_item(store, "wi-two", ["size=S"])
    assert cli.main(["--root", str(root), "check"]) == 0   # a warning, never an error
    out = capsys.readouterr().out
    assert "warning: 1 open item(s) written without a size (brain item set ID size=S|M|L|XL size_reason=...): " \
           "wi-new" in out
    assert "warning: 1 open item(s) with a size and no size_reason (brain item set ID size_reason=...): wi-two" in out
    graph.set_item(store, "wi-new", ["size=L", "size_reason=two commands"])
    graph.set_item(store, "wi-two", ["size_reason=a flag"])
    assert sizing.check_lines(store) == []


def test_a_size_off_the_scale_is_warned_and_does_not_block_other_edits(store, capsys):
    text = (store / "nodes" / "work.yaml").read_text(encoding="utf-8")
    (store / "nodes" / "work.yaml").write_text(text.replace("- {id: wi-two, type: WorkItem, status: doing, title: "
                                                            "\"Second\"}", "- {id: wi-two, type: WorkItem, status: "
                                                            "doing, title: \"Second\", props: {size: medium, "
                                                            "size_reason: hand}}"), encoding="utf-8")
    graph.set_item(store, "wi-two", ["status=todo"])   # an edit that leaves the size alone (brain wave close's)
    assert sizing.check_lines(store) == ["warning: 1 open item(s) with a size off the scale S, M, L, XL (brain item "
                                         "set ID size=...): wi-two"]
    assert sizing.hours(_nodes(store)["wi-two"]) is None
    graph.set_item(store, "wi-two", ["size=m"])
    assert sizing.check_lines(store) == []


def test_prop_size_goes_through_the_same_rules(store, capsys):
    root = store.parents[1]
    assert cli.main(["--root", str(root), "item", "add", "wi-p", "--title", "P", "--prop", "size=m", "--prop",
                     "size_reason=why"]) == 0
    assert _nodes(store)["wi-p"]["props"]["size"] == "M"
    assert cli.main(["--root", str(root), "item", "add", "wi-q", "--title", "Q", "--prop", "size=S"]) == 1
    assert cli.main(["--root", str(root), "item", "add", "wi-r", "--title", "R", "--prop", "size="]) == 0
    assert "size" not in _nodes(store)["wi-r"]["props"]


def test_generated_nodes_are_left_out(store):
    (store / "nodes" / "_generated_x.yaml").write_text(
        "- {id: wi-gen, type: WorkItem, status: todo, title: G, props: {created: \"2026-11-12\"}}\n", encoding="utf-8")
    assert sizing.unsized(store) == []


def test_hours_is_the_written_scale():
    assert [sizing.hours({"props": {"size": s}}) for s in sizing.SIZES] == [0.3, 0.8, 2.0, 4.0]
    assert sizing.hours({"props": {}}) is None
    assert sizing.hours({}) is None
