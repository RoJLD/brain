"""brain wave import (brain.waveimport): a wave per release the items' free-text props.wave names, from a release on,
the rest listed to place; on the stores of test_waves.py. Fixtures only: the owner is the tests' Ada."""
from __future__ import annotations

from test_waves import _nodes, _write

from brain import cli, waves


IMPORT_NODES = """\
- {id: ms-x, type: Milestone, status: pending, title: X}
- {id: wave-2.0.0, type: Milestone, status: pending, title: "Wave 2.0.0", props: {kind: wave, release: 2.0.0}}
- {id: wi-a, type: WorkItem, status: todo, title: A, props: {wave: "2.0.0 (Ada, 2030-01-01)"}}
- {id: wi-b, type: WorkItem, status: done, title: B, props: {wave: "v2.1.0"}}
- {id: wi-c, type: WorkItem, status: todo, title: C, props: {wave: "2.1.0, with wi-b"}}
- {id: wi-d, type: WorkItem, status: todo, title: D, props: {wave: G}}
- {id: wi-e, type: WorkItem, status: todo, title: E, props: {wave: "after the H gate"}}
- {id: wi-f, type: WorkItem, status: todo, title: F, props: {wave: "2.0.0"}}
- {id: wi-g, type: WorkItem, status: todo, title: G, props: {wave: "2.0.0.1"}}
- {id: wi-none, type: WorkItem, status: todo, title: "No wave"}
"""


def test_import_proposes_a_wave_per_release_and_lists_the_rest(tmp_path, capsys):
    store = _write(tmp_path / "root" / "notes" / "graph", IMPORT_NODES,
                   "- {from: wi-f, to: wave-2.0.0, type: part_of}\n")
    before = (store / "nodes" / "work.yaml").read_text(encoding="utf-8")
    base = ["--root", str(store.parents[1]), "wave", "import"]
    assert cli.main(base) == 0
    out = capsys.readouterr().out
    assert "2.0.0: into wave-2.0.0, 1 item(s): wi-a" in out   # wi-f is in it already
    assert "2.1.0: a new wave (wave-sN, its release pinned), 2 item(s): wi-b, wi-c" in out
    assert "to place by Ada (names no release): 'G': wi-d" in out
    assert "'after the H gate': wi-e" in out and "'2.0.0.1': wi-g" in out
    assert "not written: --write" in out
    assert (store / "nodes" / "work.yaml").read_text(encoding="utf-8") == before   # a plan only
    assert cli.main(base + ["--write"]) == 0
    capsys.readouterr()
    plan = waves.load(store)
    assert plan.items_of("wave-2.0.0") == ["wi-a", "wi-f"] and plan.items_of("wave-s2") == ["wi-b", "wi-c"]
    assert plan.resolve("2.1.0") == "wave-s2"
    new = _nodes(store)["wave-s2"]
    assert new["props"]["kind"] == "wave" and new["props"]["release"] == "2.1.0" and "brain wave import" in \
        new["props"]["decided"]
    assert _nodes(store)["wi-a"]["props"]["wave"] == "2.0.0 (Ada, 2030-01-01)"   # kept: when it was planned
    assert waves.problems(plan) == []
    assert cli.main(base) == 0   # again: nothing left but the values to place
    out = capsys.readouterr().out
    assert "new wave" not in out and "into" not in out and "'G': wi-d" in out


def test_import_from_a_release_leaves_the_earlier_ones(tmp_path, capsys):
    store = _write(tmp_path / "root" / "notes" / "graph", IMPORT_NODES, "")
    base = ["--root", str(store.parents[1]), "wave", "import", "--from", "2.1.0"]
    assert cli.main(base) == 0
    out = capsys.readouterr().out
    assert "2.1.0: a new wave (wave-sN, its release pinned), 2 item(s): wi-b, wi-c" in out
    assert "2.0.0: before --from 2.1.0, not imported: wi-a, wi-f" in out
    assert cli.main(base + ["--write"]) == 0
    capsys.readouterr()
    plan = waves.load(store)
    assert plan.items_of("wave-2.0.0") == [] and plan.items_of(plan.resolve("2.1.0")) == ["wi-b", "wi-c"]
    assert cli.main(["--root", str(store.parents[1]), "wave", "import", "--from", "2.1"]) == 1
    assert "--from 2.1: a release X.Y.Z" in capsys.readouterr().err
