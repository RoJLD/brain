"""brain wave propose (brain.propose, wi-brain-wave-propose): the next waves drafted from rank, depends_on, placements,
sizes and capacity, cut into lots; what is left out and why, the questions, the checks. Fixtures only: the owner is
the tests' Ada."""
from __future__ import annotations

import json

import pytest
from brain import cli, governor, propose, quota, waves
from test_waves import _write

# s1 reached with 4 done items (capacity: 4 items, their points 1+2+2+4 = 9), s2 pending (composed: wi-comp), an
# era whose stage is 2.0. The drafted windows are s3, s4, s5.
NODES = """\
- {id: era-one, type: Milestone, status: pending, title: Era, props: {kind: era, exit: "Go to 2.0?", stage_to: "2.0"}}
- {id: ms-core, type: Milestone, status: pending, title: Core}
- {id: wave-s1, type: Milestone, status: reached, title: S1, props: {kind: wave, seq: 1, release: 1.0.0, shipped_as: 1.0.0}}
- {id: wave-s2, type: Milestone, status: pending, title: S2, props: {kind: wave, seq: 2}}
- {id: wi-d1, type: WorkItem, status: done, title: D1, props: {size: S}}
- {id: wi-d2, type: WorkItem, status: done, title: D2, props: {size: M}}
- {id: wi-d3, type: WorkItem, status: done, title: D3, props: {size: M}}
- {id: wi-d4, type: WorkItem, status: done, title: D4, props: {size: L}}
- {id: wi-comp, type: WorkItem, status: todo, title: Composed, props: {size: M, wave_planned: "s9"}}
- {id: wi-p1, type: WorkItem, status: todo, title: P1 first, props: {priority: P1, size: M}}
- {id: wi-a, type: WorkItem, status: todo, title: A, props: {priority: P2, size: S}}
- {id: wi-b, type: WorkItem, status: todo, title: B after A, props: {priority: P2, size: S}}
- {id: wi-pin4, type: WorkItem, status: todo, title: Pinned s4, props: {priority: P3, size: S, wave_planned: "s4"}}
- {id: wi-late, type: WorkItem, status: todo, title: Overdue pin, props: {priority: P3, size: S, wave_planned: "s2"}}
- {id: wi-held, type: WorkItem, status: todo, title: The composed one waits on it, props: {priority: P3, size: S}}
- {id: wi-due, type: WorkItem, status: todo, title: Due before 2.0, props: {priority: P3, size: S, place: "before 2.0"}}
- {id: wi-pair, type: WorkItem, status: todo, title: Pair, props: {priority: P2, size: S, place: "with wi-mate"}}
- {id: wi-mate, type: WorkItem, status: todo, title: Mate, props: {priority: P3, size: S, place: "with wi-pair"}}
- {id: wi-door, type: WorkItem, status: todo, title: Door, props: {priority: P2, size: S, door: format,
   place: "wave s5; own-lot"}}
- {id: wi-owner, type: WorkItem, status: todo, title: Owner, props: {priority: P1, track: "owner (out of waves)"}}
- {id: wi-ext, type: WorkItem, status: todo, title: Ext, props: {priority: P1, external_blocker: "Ada signs"}}
- {id: wi-blocked, type: WorkItem, status: blocked, title: Blocked, props: {priority: P1}}
- {id: wi-later, type: WorkItem, status: todo, title: Later, props: {priority: P1, place: "out later"}}
- {id: wi-post, type: WorkItem, status: todo, title: Post, props: {priority: P1, place: "after 2.0"}}
- {id: wi-far, type: WorkItem, status: todo, title: Far, props: {priority: P1, place: "wave s9"}}
- {id: wi-c1, type: WorkItem, status: todo, title: C1, props: {priority: P1}}
- {id: wi-c2, type: WorkItem, status: todo, title: C2, props: {priority: P1}}
- {id: wi-debt, type: WorkItem, status: todo, title: Debt, props: {standing: "true"}}
- {id: wi-low, type: WorkItem, status: todo, title: Low, props: {priority: P3, size: XL}}
"""

EDGES = """\
- {from: ms-core, to: era-one, type: part_of}
- {from: wave-s1, to: ms-core, type: part_of}
- {from: wave-s2, to: ms-core, type: part_of}
- {from: wi-d1, to: wave-s1, type: part_of}
- {from: wi-d2, to: wave-s1, type: part_of}
- {from: wi-d3, to: wave-s1, type: part_of}
- {from: wi-d4, to: wave-s1, type: part_of}
- {from: wi-comp, to: wave-s2, type: part_of}
- {from: wi-comp, to: wi-held, type: depends_on}
- {from: wi-b, to: wi-a, type: depends_on}
- {from: wi-c1, to: wi-c2, type: depends_on}
- {from: wi-c2, to: wi-c1, type: depends_on}
"""


@pytest.fixture(autouse=True)
def _no_machine(monkeypatch):
    monkeypatch.setattr(governor, "memory_info", lambda: {"committed": 40.0, "available_gb": 30.0})
    monkeypatch.setattr(quota, "load_status", lambda: {})


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    _write(r / "notes" / "graph", NODES, EDGES)
    return r


def _prop(root, **kw):
    return propose.propose(root / "notes" / "graph", root, **kw)


def _where(prop) -> dict[str, str]:
    return {r["id"]: f"s{w.seq}" for w in prop.waves for r in w.items}


def test_the_capacity_is_what_the_last_reached_waves_closed(root):
    plan = waves.load(root / "notes" / "graph", root)
    assert propose.capacity(plan) == {"items": 4, "points": 9, "basis": "the median of the last 1 reached wave(s)",
                                      "quick_wins": 1}
    assert propose.capacity(plan, 6, 20)["basis"] == "given"


def test_the_out_list_says_why(root):
    prop = _prop(root, items=8, pts=30)
    why = {r["id"]: r["why"] for r in prop.out}
    assert why["wi-owner"] == "owner" and why["wi-ext"] == "external: Ada signs" and why["wi-blocked"] == "blocked"
    assert why["wi-later"] == "later" and why["wi-post"] == "after 2.0 (no wave named)"
    assert why["wi-far"] == "pinned to s9, beyond the drafted waves"
    assert why["wi-c1"] == why["wi-c2"] == "a depends_on cycle"
    assert any("a depends_on cycle: wi-c1, wi-c2" in q for q in prop.questions)
    assert "wi-comp" not in why and "wi-comp" not in _where(prop)   # composed in s2: the plan's fact


def test_the_fill_honours_pins_dependencies_and_pairs(root):
    prop = _prop(root, items=8, pts=30)
    at = _where(prop)
    assert [w.seq for w in prop.waves] == [3, 4, 5]
    assert at["wi-pin4"] == "s4" and at["wi-door"] == "s5"
    assert at["wi-late"] == "s3" and at["wi-held"] == "s3"   # overdue, and held by a composed item: first
    assert any("wi-late is pinned to s2, which was composed without it" in q for q in prop.questions)
    assert any("wi-comp (composed in s2) waits on wi-held" in q for q in prop.questions)
    assert at["wi-a"] == at["wi-b"] == "s3"   # stacked in one wave: a chain of 2
    assert at["wi-pair"] == at["wi-mate"]
    assert at["wi-due"] == "s3" and prop.eras[0]["placed"] == {"wi-due": "s3"}
    assert prop.checks == []
    seen = [r["id"] for w in prop.waves for r in w.items]
    assert len(seen) == len(set(seen))
    assert all(w.standing == ["wi-debt"] for w in prop.waves)


def test_the_capacity_holds_and_the_rest_waits(root):
    prop = _prop(root, items=3, pts=30, n=2)
    assert [[r["id"] for r in w.items] for w in prop.waves] == [["wi-held", "wi-late", "wi-due"],   # due first
                                                                 ["wi-pin4", "wi-p1", "wi-a"]]       # then by rank
    why = {r["id"]: r["why"] for r in prop.out}
    assert why["wi-low"] == why["wi-b"] == why["wi-pair"] == "capacity"
    assert why["wi-door"] == "pinned to s5, beyond the drafted waves"


def test_doors_make_a_minor_and_own_lot_stands_alone(root):
    prop = _prop(root, items=8, pts=30)
    s3, s4, s5 = prop.waves
    assert (s3.release, s3.kind) == ("1.0.2", "patch") and (s4.release, s5.release) == ("1.0.3", "1.1.0")
    assert s5.kind == "minor" and s5.doors == ["wi-door"]
    assert ["wi-door"] in [lot["items"] for lot in s5.lots]
    assert all(len(w.lots) <= propose.MAX_LOTS for w in prop.waves)


def test_brain_wave_propose_text_json_and_against(root, tmp_path, capsys):
    base = ["--root", str(root), "wave", "propose", "--items", "8", "--points", "30", "--no-merged"]
    assert cli.main(base) == 0
    out = capsys.readouterr().out
    assert out.startswith("brain wave propose: 3 wave(s) after 1.0.1")
    assert "wave-s5 (1.1.0, minor)" in out and "standing: wi-debt (a batch)" in out
    assert "  wi-owner: owner" in out and "questions (" in out
    assert cli.main(base + ["--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["format"] == 1 and [w["id"] for w in rep["waves"]] == ["wave-s3", "wave-s4", "wave-s5"]
    rep["waves"][0]["items"] = rep["waves"][0]["items"][1:]
    old = tmp_path / "old.json"
    old.write_text(json.dumps(rep), encoding="utf-8")
    assert cli.main(base + ["--against", str(old)]) == 0
    assert "since the earlier proposal, s3: +" in capsys.readouterr().out
    assert cli.main(base + ["--from", "wave-nothing"]) == 1
    assert "no wave of that release or id" in capsys.readouterr().err
