"""brain.waverename (wi-brain-wave-ids-decoupled, WAVES-5): a legacy wave renamed once, on the stores of test_waves.py
(the command's own test there: test_rename_once_rewrites_the_references_and_keeps_the_old_id)."""
from __future__ import annotations

import pytest
from test_waves import JUMP_EDGES, JUMP_NODES, _nodes, _write

from brain import graph, waverename, waves


def _ends_known(store) -> list[str]:
    """The edges (the generated ones included) whose from or to is no node of the store: what keeps it from loading."""
    nodes = set(graph.node_index(store))
    edges = [e for f in [store / "edges.yaml", *sorted((store / "edges").glob("*.yaml"))] if f.is_file()
             for e in (graph.load_yaml_list(f) or []) if isinstance(e, dict)]
    return [f"{e['from']} -> {e['to']}" for e in edges if e.get("from") not in nodes or e.get("to") not in nodes]


def test_a_reached_wave_keeps_its_release_and_its_generated_files_follow(tmp_path):
    store = _write(tmp_path / "graph", JUMP_NODES, JUMP_EDGES + "- {from: wave-1.0.0, to: ms-x, type: part_of}\n")
    (store / "edges" / "_generated_links.yaml").write_text("- {from: ms-x, to: wave-1.0.0, type: about}\n",
                                                           encoding="utf-8")
    plan = waverename.rename(store, "1.0.0")
    assert plan.new == "wave-s1" and plan.files == {"edges/work.yaml": 1, "nodes/work.yaml": 1}
    assert plan.generated == {"edges/_generated_links.yaml": 1} and plan.title == "Wave s1"
    done = waverename.rename(store, "wave-1.0.0", write=True, today="2030-01-01")
    assert done.release == "1.0.0"   # a reached wave keeps props.release: its label does not move
    node = _nodes(store)["wave-s1"]
    assert node["props"]["release"] == "1.0.0" and node["props"]["renamed_from"] == \
        "wave-1.0.0 (brain wave rename, 2030-01-01)"
    assert node["title"] == "Wave s1"   # its default title named the old release
    assert "wave-1.0.0" not in (store / "edges" / "_generated_links.yaml").read_text(encoding="utf-8")
    assert _ends_known(store) == []   # the store loads before brain sync
    after = waves.load(store)
    assert after.resolve("wave-1.0.0") == "wave-s1" and after.waves[:2] == ["wave-s1", "wave-1.0.1"]
    assert waves.problems(after) == []


def test_only_the_values_are_rewritten(tmp_path):
    """A comment and a free text that name the old id are left; carried_to and each carried_via id are rewritten; a
    title the owner wrote is kept."""
    nodes = JUMP_NODES.replace('title: "Wave 1.0.1"', 'title: "Patch week"').replace(
        "title: Later}", 'title: "Later, after wave-1.0.1", props: {carried_to: wave-s4, '
                         'carried_via: "wave-1.0.1, wave-s3"}}') + "# wave-1.0.1 was planned on Monday\n"
    store = _write(tmp_path / "graph", nodes, JUMP_EDGES)
    r = waverename.rename(store, "wave-1.0.1", write=True, today="2030-01-01")
    text = (store / "nodes" / "work.yaml").read_text(encoding="utf-8")
    assert "# wave-1.0.1 was planned on Monday" in text and '"Later, after wave-1.0.1"' in text
    assert _nodes(store)["wi-later"]["props"]["carried_via"] == "wave-s2, wave-s3" and r.title == ""
    assert _nodes(store)["wave-s2"]["title"] == "Patch week" and _ends_known(store) == []


def test_a_second_rename_keeps_the_first_id(tmp_path):
    store = _write(tmp_path / "graph", JUMP_NODES, JUMP_EDGES)
    waverename.rename(store, "wave-1.0.1", "wave-next", write=True, today="2030-01-01")
    waverename.rename(store, "wave-next", "wave-later", write=True, today="2030-01-02")
    said = _nodes(store)["wave-later"]["props"]["renamed_from"]
    assert said.startswith("wave-next (brain wave rename, 2030-01-02); before: wave-1.0.1 (brain wave rename")
    plan = waves.load(store)
    assert plan.resolve("wave-1.0.1") == "wave-later" and plan.resolve("wave-next") == "wave-later"


@pytest.mark.parametrize("new, why", [("wave-1.x", "no dot"), ("Wave-S9", "no dot"), ("wave-s3", "already a node"),
                                      ("wave-first", "a former id of wave-s1")])
def test_a_new_id_with_a_version_or_taken_is_refused(tmp_path, new, why):
    store = _write(tmp_path / "graph", JUMP_NODES, JUMP_EDGES)
    waverename.rename(store, "wave-1.0.0", "wave-first", write=True, today="2030-01-01")
    waverename.rename(store, "wave-first", write=True, today="2030-01-01")   # wave-first: wave-s1's former id
    with pytest.raises(waves.WaveError, match=why):
        waverename.rename(store, "wave-1.0.1", new)
    with pytest.raises(waves.WaveError, match="no wave of that id or release"):
        waverename.rename(store, "9.9.9")


@pytest.mark.parametrize("said, ids", [
    ("wave-1.0.1 (brain wave rename, 2030-01-01)", ["wave-1.0.1"]),
    ("wave-next (brain wave rename, 2030-01-02); before: wave-1.0.1 (brain wave rename)", ["wave-next", "wave-1.0.1"]),
    ("wave-a, wave-b (by hand); BEFORE: wave-c.", ["wave-a", "wave-b", "wave-c"]),   # commas, any case, a full stop
    ("wave-s3.", ["wave-s3"]), ("not a wave id", []),
])
def test_the_former_ids_a_renamed_from_names(said, ids):
    plan = waves.Plan({"wave-x": {"id": "wave-x", "type": "Milestone", "props": {"kind": "wave", "renamed_from": said}}})
    assert plan.former("wave-x") == ids
