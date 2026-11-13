"""brain.waverename (wi-brain-wave-ids-decoupled, WAVES-5): a legacy wave renamed once, on the stores of test_waves.py
(the command's own test there: test_rename_once_rewrites_the_references_and_keeps_the_old_id)."""
from __future__ import annotations

import pytest
from test_waves import JUMP_EDGES, JUMP_NODES, _nodes, _write

from brain import waverename, waves


def test_a_reached_wave_keeps_its_release_and_its_generated_files_are_left(tmp_path):
    store = _write(tmp_path / "graph", JUMP_NODES, JUMP_EDGES + "- {from: wave-1.0.0, to: ms-x, type: part_of}\n")
    (store / "edges" / "_generated_links.yaml").write_text("- {from: x, to: wave-1.0.0, type: about}\n",
                                                           encoding="utf-8")
    plan = waverename.rename(store, "1.0.0")
    assert plan.new == "wave-s1" and plan.files == {"edges/work.yaml": 1, "nodes/work.yaml": 1}   # not _generated
    done = waverename.rename(store, "wave-1.0.0", write=True, today="2030-01-01")
    assert done.release == "1.0.0"   # a reached wave keeps props.release: its label does not move
    node = _nodes(store)["wave-s1"]
    assert node["props"]["release"] == "1.0.0" and node["props"]["renamed_from"] == \
        "wave-1.0.0 (brain wave rename, 2030-01-01)"
    assert "wave-1.0.0" in (store / "edges" / "_generated_links.yaml").read_text(encoding="utf-8")
    after = waves.load(store)
    assert after.resolve("wave-1.0.0") == "wave-s1" and after.waves[:2] == ["wave-s1", "wave-1.0.1"]


def test_a_second_rename_keeps_the_first_id(tmp_path):
    store = _write(tmp_path / "graph", JUMP_NODES, JUMP_EDGES)
    waverename.rename(store, "wave-1.0.1", "wave-next", write=True, today="2030-01-01")
    waverename.rename(store, "wave-next", "wave-later", write=True, today="2030-01-02")
    said = _nodes(store)["wave-later"]["props"]["renamed_from"]
    assert said.startswith("wave-next (brain wave rename, 2030-01-02); before: wave-1.0.1 (brain wave rename")
    plan = waves.load(store)
    assert plan.resolve("wave-1.0.1") == "wave-later" and plan.resolve("wave-next") == "wave-later"


@pytest.mark.parametrize("new, why", [("wave-1.x", "no dot"), ("Wave-S9", "no dot"), ("wave-s3", "already a node")])
def test_a_new_id_with_a_version_or_taken_is_refused(tmp_path, new, why):
    store = _write(tmp_path / "graph", JUMP_NODES, JUMP_EDGES)
    with pytest.raises(waves.WaveError, match=why):
        waverename.rename(store, "wave-1.0.1", new)
    with pytest.raises(waves.WaveError, match="no wave of that id or release"):
        waverename.rename(store, "9.9.9")
