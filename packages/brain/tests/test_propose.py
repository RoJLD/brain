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


def test_merged_items_count_done_and_a_standing_one_stays(root, monkeypatch):
    found = {"wi-a": ["brain #1"], "wi-debt": ["brain #2"]}
    monkeypatch.setattr(propose.lots, "merged_of", lambda plan, wid, repos: ({}, found))
    prop = _prop(root, items=8, pts=30, repos=[("brain", root)])
    assert prop.merged == ["wi-a"]
    assert "wi-a" not in _where(prop) and "wi-a" not in {r["id"] for r in prop.out}
    assert _where(prop)["wi-b"] == "s3"   # its prerequisite merged: satisfied
    assert all(w.standing == ["wi-debt"] for w in prop.waves)


# A small store for the review's cases: s1 reached, s2 pending with wi-comp composed; the windows are s3, s4, s5.
BASE = """\
- {id: wave-s1, type: Milestone, status: reached, title: S1, props: {kind: wave, seq: 1, release: 1.0.0, shipped_as: 1.0.0}}
- {id: wave-s2, type: Milestone, status: pending, title: S2, props: {kind: wave, seq: 2}}
- {id: wi-d1, type: WorkItem, status: done, title: D1, props: {size: S}}
- {id: wi-comp, type: WorkItem, status: todo, title: Composed, props: {size: M}}
"""
BASE_EDGES = """\
- {from: wi-d1, to: wave-s1, type: part_of}
- {from: wi-comp, to: wave-s2, type: part_of}
"""


def _small(tmp_path, nodes: str, edges: str = "", **kw):
    r = tmp_path / "small"
    _write(r / "notes" / "graph", BASE + nodes, BASE_EDGES + edges)
    return propose.propose(r / "notes" / "graph", r, **kw)


def test_an_after_placement_is_a_prerequisite_in_an_earlier_wave(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-x, type: WorkItem, status: todo, title: X, props: {priority: P3, size: S, place: "earliest s4"}}
- {id: wi-y, type: WorkItem, status: todo, title: Y, props: {priority: P1, size: S, place: "after wi-x"}}
- {id: wi-z, type: WorkItem, status: todo, title: Z, props: {priority: P1, size: S, place: "after wi-d1"}}
""", items=5, pts=30)
    at = _where(prop)
    assert at["wi-x"] == "s4" and at["wi-y"] == "s5"   # after the wave of wi-x, never in it nor before
    assert at["wi-z"] == "s3"                         # after a done item: nothing to wait on
    assert prop.checks == []


def test_an_after_item_never_shares_its_wave(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-x, type: WorkItem, status: todo, title: X, props: {priority: P1, size: S}}
- {id: wi-y, type: WorkItem, status: todo, title: Y, props: {priority: P1, size: S, place: "after wi-x"}}
""", items=5, pts=30, n=1)
    assert _where(prop) == {"wi-x": "s3"}
    assert {r["id"]: r["why"] for r in prop.out}["wi-y"] == "after: wi-x not placed in a wave before s3"


def test_a_choice_bounds_the_item_to_its_waves(tmp_path):
    nodes = """\
- {id: wi-h1, type: WorkItem, status: todo, title: H1, props: {priority: P1, size: M}}
- {id: wi-h2, type: WorkItem, status: todo, title: H2, props: {priority: P1, size: M}}
- {id: wi-ch, type: WorkItem, status: todo, title: Choice, props: {priority: P3, size: M, place: "wave s3 or s4"}}
"""
    prop = _small(tmp_path, nodes, items=1, pts=30, n=3)
    assert "wi-ch" not in _where(prop)   # s3 and s4 full: out, never drafted in s5
    assert {r["id"]: r["why"] for r in prop.out}["wi-ch"] == "capacity"
    assert prop.checks == []
    prop = _small(tmp_path, nodes, items=2, pts=30, n=3)
    assert _where(prop)["wi-ch"] == "s4"   # s3 full: the other wave of its choice


def test_a_missed_deadline_is_placed_and_asked(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-f1, type: WorkItem, status: todo, title: F1, props: {priority: P1, size: S, wave_planned: "s3"}}
- {id: wi-lt, type: WorkItem, status: todo, title: Overdue, props: {priority: P3, size: S, place: "latest s2"}}
- {id: wi-l3, type: WorkItem, status: todo, title: Due s3, props: {priority: P3, size: S, place: "latest s3"}}
""", items=1, pts=30, n=3)
    assert _where(prop) == {"wi-f1": "s3", "wi-lt": "s4", "wi-l3": "s5"}
    assert "wi-lt is due by s2, before the drafted waves: drafted in s4, first" in prop.questions
    assert "wi-l3 is due by s3: no room there, drafted in s5" in prop.questions


def test_from_an_earlier_wave_counts_a_composed_window(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-f1, type: WorkItem, status: todo, title: F1, props: {priority: P1, size: S}}
""", items=1, pts=30, n=2, start="wave-s1")
    s2, s3 = prop.waves
    assert (s2.id, [(r["id"], r["why"]) for r in s2.items]) == ("wave-s2", [("wi-comp", "composed")])
    assert s2.size["items"] == 1 and [r["id"] for r in s3.items] == ["wi-f1"]
    assert not [r for r in prop.risks if "over its capacity" in r]


def test_a_with_partner_done_or_out_asks_no_false_question(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-dn, type: WorkItem, status: done, title: Done, props: {size: S}}
- {id: wi-pa, type: WorkItem, status: todo, title: Pa, props: {priority: P1, size: S, place: "with wi-dn, wi-ow"}}
- {id: wi-ow, type: WorkItem, status: todo, title: Ow, props: {priority: P1, track: "owner (out of waves)"}}
""", items=5, pts=30)
    assert _where(prop)["wi-pa"] == "s3"
    assert not [q for q in prop.questions if "could not follow" in q]
    assert "wi-pa goes with wi-ow, which is out (owner)" in prop.questions


def test_a_first_item_keeps_its_place_when_its_prerequisite_comes_in(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-late, type: WorkItem, status: todo, title: Late, props: {priority: P1, size: M, wave_planned: "s2"}}
- {id: wi-pre, type: WorkItem, status: todo, title: Pre, props: {priority: P3, size: M}}
- {id: wi-r1, type: WorkItem, status: todo, title: R1, props: {priority: P2, size: M}}
- {id: wi-gone, type: WorkItem, status: todo, title: Gone, props: {priority: P1, size: XL, wave_planned: "s2"}}
""", "- {from: wi-late, to: wi-pre, type: depends_on}\n", items=8, pts=4, n=1)
    assert _where(prop) == {"wi-pre": "s3", "wi-late": "s3"}   # its prerequisite lifted, before the higher wi-r1
    assert "wi-late is pinned to s2, which was composed without it: drafted in s3, first" in prop.questions
    assert "wi-gone is pinned to s2, which was composed without it: in no drafted wave (capacity)" in prop.questions


def test_against_a_file_of_another_shape_is_an_error(root, tmp_path, capsys):
    prop = _prop(root, items=8, pts=30)
    f = tmp_path / "bad.json"
    for bad in ([1], {"waves": [{"items": []}]}, {"waves": [{"seq": 3, "items": [1]}]}, {"waves": 3}):
        f.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="not a brain wave propose --json"):
            propose.against(prop, f)
    assert cli.main(["--root", str(root), "wave", "propose", "--no-merged", "--against", str(f)]) == 1
    assert "not a brain wave propose --json" in capsys.readouterr().err


def test_a_chain_stacked_across_modules_joins_no_cycle_of_lots(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-ca, type: WorkItem, status: todo, title: CA, props: {priority: P1, size: S, module: m1}}
- {id: wi-cb, type: WorkItem, status: todo, title: CB, props: {priority: P1, size: S, module: m2}}
- {id: wi-cc, type: WorkItem, status: todo, title: CC, props: {priority: P1, size: S, module: m1}}
""", "- {from: wi-cb, to: wi-ca, type: depends_on}\n- {from: wi-cc, to: wi-cb, type: depends_on}\n",
        items=8, pts=30, n=1)
    s3 = prop.waves[0]
    assert sorted(r["id"] for r in s3.items) == ["wi-ca", "wi-cb", "wi-cc"]
    rounds = {i: r for r, ns in enumerate(s3.rounds) for n in ns for i in s3.lots[n - 1]["items"]}
    assert rounds["wi-ca"] < rounds["wi-cb"] < rounds["wi-cc"]


def _units(after: dict[str, list[str]], files: dict[str, list[str]] | None = None):
    return {i: propose.lots.Unit(i, i, "todo", "P2", files=(files or {}).get(i, []), after=a)
            for i, a in after.items()}


def test_an_own_lot_item_in_the_middle_of_a_chain_splits_its_lot_without_a_cycle():
    lot_ = propose.lots.Lot
    units = _units({"a": [], "x": ["a"], "b": ["x"], "c": []}, {i: ["f.py"] for i in "axbc"})
    found = propose._alone([lot_(0, ["a", "x", "b", "c"], ["f.py"], [], 0, True)], units, {"x"})
    assert sorted(sorted(lot.items) for lot in found) == [["a"], ["b", "c"], ["x"]]
    assert not propose._cyclic(found, units)
    found = propose._alone([lot_(0, ["a", "x", "c"], ["f.py"], [], 0, True)], units, {"x"})
    assert sorted(sorted(lot.items) for lot in found) == [["a", "c"], ["x"]]   # no cycle: the rest stays one lot


def test_the_lots_gathered_to_six_never_join_into_a_cycle():
    after = {"a": [], "c": ["b"], "b": ["a"]} | {f"z{n}": [] for n in range(6)}   # a and c first: a cycle if joined
    units = _units(after)
    found = [propose.lots.Lot(0, [i], [], [], 0, True) for i in after]
    plan = type("Plan", (), {"nodes": {}})()
    out = propose._grouped(plan, found, units, set())
    assert len(out) <= propose.MAX_LOTS and not propose._cyclic(out, units)
    assert propose.lots.rounds_of(out, units, 3)


def test_a_pinned_items_prerequisite_is_lifted_before_higher_ranked_items(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-p, type: WorkItem, status: todo, title: P, props: {priority: P3, size: S, wave_planned: "s3"}}
- {id: wi-d, type: WorkItem, status: todo, title: D, props: {priority: P3, size: S}}
- {id: wi-h, type: WorkItem, status: todo, title: H, props: {priority: P1, size: S}}
""", "- {from: wi-p, to: wi-d, type: depends_on}\n", items=2, pts=30, n=2)
    assert _where(prop) == {"wi-p": "s3", "wi-d": "s3", "wi-h": "s4"}   # the same wave, within the chain cap
    assert prop.checks == [] and not [q for q in prop.questions if "is pinned to s3, but" in q]


@pytest.mark.parametrize("place,edge", [('wave_planned: "s4"', "- {from: wi-p, to: wi-dd, type: depends_on}\n"),
                                        ('place: "wave s4; after wi-dd"', "")])
def test_a_later_pins_prerequisite_comes_in_an_earlier_wave(tmp_path, place, edge):
    prop = _small(tmp_path, f"""\
- {{id: wi-p, type: WorkItem, status: todo, title: P, props: {{priority: P3, size: S, {place}}}}}
- {{id: wi-dd, type: WorkItem, status: todo, title: DD, props: {{priority: P3, size: S}}}}
- {{id: wi-h1, type: WorkItem, status: todo, title: H1, props: {{priority: P1, size: S}}}}
- {{id: wi-h2, type: WorkItem, status: todo, title: H2, props: {{priority: P1, size: S}}}}
""", edge, items=2, pts=30, n=3)
    at = _where(prop)
    assert at["wi-p"] == "s4" and at["wi-dd"] == "s3"
    assert prop.checks == []


def test_a_pin_whose_prerequisite_is_out_is_a_check_and_a_question(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-p, type: WorkItem, status: todo, title: P, props: {priority: P3, size: S, wave_planned: "s3"}}
- {id: wi-ob, type: WorkItem, status: todo, title: Ob, props: {priority: P1, track: "owner (out of waves)"}}
""", "- {from: wi-p, to: wi-ob, type: depends_on}\n", items=5, pts=30, n=1)
    assert _where(prop) == {"wi-p": "s3"}
    assert prop.checks == ["wi-p (s3) before its prerequisite wi-ob (in no drafted wave)"]
    assert "wi-p is pinned to s3, but wi-ob not placed before s3" in prop.questions


def test_from_an_earlier_wave_keeps_the_composed_waves_release(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-cd, type: WorkItem, status: todo, title: Composed door, props: {size: S, door: format}}
- {id: wi-f1, type: WorkItem, status: todo, title: F1, props: {priority: P1, size: S}}
""", "- {from: wi-cd, to: wave-s2, type: part_of}\n", items=4, pts=30, n=2, start="wave-s1")
    s2, s3 = prop.waves
    assert (s2.id, s2.release, s2.kind) == ("wave-s2", "1.0.1", "patch")   # the plan's label, not a computed minor
    assert s2.exit[-1] == "tag v1.0.1" and (s3.release, s3.kind) == ("1.0.2", "patch")
    default = _small(tmp_path, "- {id: wi-cd, type: WorkItem, status: todo, title: Cd, props: {size: S, door: x}}\n",
                     "- {from: wi-cd, to: wave-s2, type: part_of}\n", items=4, pts=30, n=1)
    assert default.start == "1.0.1" and default.waves[0].release == "1.0.2"


@pytest.mark.parametrize("own", ["", ', place: "own-lot"'])
def test_a_cycle_of_composed_items_in_a_window_crashes_nothing(tmp_path, own):
    prop = _small(tmp_path, f"""\
- {{id: wi-c2, type: WorkItem, status: todo, title: C2, props: {{size: S{own}}}}}
- {{id: wi-n, type: WorkItem, status: todo, title: N, props: {{priority: P1, size: S}}}}
- {{id: wi-m, type: WorkItem, status: todo, title: M, props: {{priority: P1, size: S}}}}
""", """\
- {from: wi-c2, to: wave-s2, type: part_of}
- {from: wi-comp, to: wi-c2, type: depends_on}
- {from: wi-c2, to: wi-comp, type: depends_on}
- {from: wi-n, to: wi-comp, type: depends_on}
- {from: wi-m, to: wi-n, type: depends_on}
""", items=5, pts=30, n=2, start="wave-s1")
    s2 = prop.waves[0]
    assert {"wi-c2", "wi-comp"} <= {r["id"] for r in s2.items} and s2.rounds
    assert _where(prop)["wi-n"] == "s2" and prop.checks == []   # after the cycle, in the same wave: its chain counted
    assert any(q.startswith("a depends_on cycle: wi-c2, wi-comp") and "composed, kept" in q for q in prop.questions)


def test_a_cycle_through_a_composed_item_leaves_the_drafted_ones_out(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-a, type: WorkItem, status: todo, title: A, props: {priority: P1, size: S, place: "own-lot"}}
- {id: wi-b, type: WorkItem, status: todo, title: B, props: {priority: P1, size: S}}
""", """\
- {from: wi-a, to: wi-b, type: depends_on}
- {from: wi-b, to: wi-comp, type: depends_on}
- {from: wi-comp, to: wi-a, type: depends_on}
""", items=5, pts=20, n=1)
    why = {r["id"]: r["why"] for r in prop.out}
    assert why["wi-a"] == why["wi-b"] == "a depends_on cycle" and _where(prop) == {}
    assert any(q.startswith("a depends_on cycle: wi-a, wi-b, wi-comp") for q in prop.questions)


def test_the_lots_drop_a_cycle_inside_a_wave():
    units = _units({"x": ["y"], "y": ["x"], "z": ["x"]})
    propose._acyclic(units)
    assert units["x"].after == units["y"].after == [] and units["z"].after == ["x"]


@pytest.mark.parametrize("nodes,kw", [
    ('- {id: wi-t, type: WorkItem, status: todo, title: T, props: {priority: P1, size: S}}\n'
     '- {id: wi-i, type: WorkItem, status: todo, title: I, props: {priority: P2, size: S, place: "earliest s4; with '
     'wi-t"}}\n', {"items": 5}),
    ('- {id: wi-t, type: WorkItem, status: todo, title: T, props: {priority: P1, size: S}}\n'
     '- {id: wi-o, type: WorkItem, status: todo, title: O, props: {priority: P1, size: S}}\n'
     '- {id: wi-i, type: WorkItem, status: todo, title: I, props: {priority: P2, size: S, place: "with wi-t"}}\n',
     {"items": 2})])
def test_a_with_pair_split_across_waves_is_asked(tmp_path, nodes, kw):
    prop = _small(tmp_path, nodes, pts=30, n=2, **kw)
    at = _where(prop)
    assert at["wi-t"] == "s3" and at["wi-i"] == "s4"
    assert "wi-i (s4) goes with wi-t, drafted in s3" in prop.questions


def test_a_with_partner_that_comes_in_later_in_the_wave_asks_nothing(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-i, type: WorkItem, status: todo, title: I, props: {priority: P1, size: S, place: "with wi-t"}}
- {id: wi-t, type: WorkItem, status: todo, title: T, props: {priority: P3, size: S}}
- {id: wi-u, type: WorkItem, status: todo, title: U, props: {priority: P2, size: S}}
- {id: wi-v, type: WorkItem, status: todo, title: V, props: {priority: P2, size: S}}
""", "- {from: wi-t, to: wi-u, type: depends_on}\n", items=3, pts=30, n=2)
    assert _where(prop) == {"wi-i": "s3", "wi-u": "s3", "wi-t": "s3", "wi-v": "s4"}   # the partner before wi-v
    assert not [q for q in prop.questions if "goes with" in q]


def test_an_item_after_a_standing_one_is_drafted(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-debt, type: WorkItem, status: todo, title: Debt, props: {standing: "true", wave_planned: "s3"}}
- {id: wi-a, type: WorkItem, status: todo, title: A, props: {priority: P1, size: S}}
""", "- {from: wi-a, to: wi-debt, type: depends_on}\n", items=5, pts=20, n=2)
    assert _where(prop) == {"wi-a": "s3"} and prop.checks == []
    assert all(w.standing == ["wi-debt"] for w in prop.waves)


@pytest.mark.parametrize("place,edge", [('wave_planned: "s4"', "- {from: wi-p, to: wi-dd, type: depends_on}\n"),
                                        ('place: "wave s4; after wi-dd"', "")])
def test_a_later_pins_prerequisite_comes_before_the_overdue_items(tmp_path, place, edge):
    prop = _small(tmp_path, f"""\
- {{id: wi-p, type: WorkItem, status: todo, title: P, props: {{priority: P3, size: S, {place}}}}}
- {{id: wi-dd, type: WorkItem, status: todo, title: DD, props: {{priority: P3, size: S}}}}
- {{id: wi-h1, type: WorkItem, status: todo, title: H1, props: {{priority: P1, size: S, wave_planned: "s2"}}}}
- {{id: wi-h2, type: WorkItem, status: todo, title: H2, props: {{priority: P1, size: S, wave_planned: "s2"}}}}
""", edge, items=2, pts=30, n=3)
    at = _where(prop)
    assert at["wi-dd"] == "s3" and at["wi-p"] == "s4"   # due by the wave before the pin's: ahead of the overdue ones
    assert {at["wi-h1"], at["wi-h2"]} == {"s3", "s4"}
    assert prop.checks == []


def test_a_choices_prerequisite_is_lifted_so_the_choice_holds(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-ch, type: WorkItem, status: todo, title: Choice, props: {priority: P1, size: S, place: "wave s3 or s4"}}
- {id: wi-pre, type: WorkItem, status: todo, title: Pre, props: {priority: P3, size: S}}
- {id: wi-h1, type: WorkItem, status: todo, title: H1, props: {priority: P1, size: S}}
- {id: wi-h2, type: WorkItem, status: todo, title: H2, props: {priority: P1, size: S}}
- {id: wi-h3, type: WorkItem, status: todo, title: H3, props: {priority: P2, size: S}}
- {id: wi-h4, type: WorkItem, status: todo, title: H4, props: {priority: P2, size: S}}
""", "- {from: wi-ch, to: wi-pre, type: depends_on}\n", items=2, pts=30, n=3)
    at = _where(prop)
    assert at["wi-pre"] == "s3" and at["wi-ch"] in ("s3", "s4")
    assert prop.checks == []


def test_a_choice_that_misses_its_waves_is_asked(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-ch, type: WorkItem, status: todo, title: Choice, props: {priority: P1, size: S, place: "wave s3 or s4"}}
- {id: wi-p3, type: WorkItem, status: todo, title: P3, props: {priority: P3, size: S, wave_planned: "s3"}}
- {id: wi-p4, type: WorkItem, status: todo, title: P4, props: {priority: P3, size: S, wave_planned: "s4"}}
""", items=1, pts=30, n=3)
    assert "wi-ch" not in _where(prop)
    assert "wi-ch's choice of waves, s3 or s4: in no drafted wave (capacity)" in prop.questions


def test_a_standing_item_composed_in_a_window_is_the_batch_only(tmp_path):
    prop = _small(tmp_path, """\
- {id: wi-debt, type: WorkItem, status: todo, title: Debt, props: {standing: "true", size: M}}
- {id: wi-f1, type: WorkItem, status: todo, title: F1, props: {priority: P1, size: S}}
""", "- {from: wi-debt, to: wave-s2, type: part_of}\n", items=2, pts=30, n=2, start="wave-s1")
    s2, s3 = prop.waves
    assert [r["id"] for r in s2.items] == ["wi-comp", "wi-f1"] and s2.standing == ["wi-debt"]
    assert "wi-debt" not in {i for lot in s2.lots for i in lot["items"]} and s2.size["items"] == 2
    assert all(w.standing == ["wi-debt"] for w in prop.waves)
