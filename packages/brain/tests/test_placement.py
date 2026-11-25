"""Placements as constraints (brain.placement, wi-brain-placement-grammar): the strict props.place (format v1) and the
placement words of the free text (wave_planned, planned_wave, wave_fit, wave, after_1_0, decided_*, track), resolved
to wave places; brain wave placements and brain check's warnings. Fixtures only: the owner is the tests' Ada."""
from __future__ import annotations

import json

import pytest
from test_waves import _write

from brain import cli, placement, waves

# Two reached waves (1.0.0, 1.1.0), two pending ones (s3, s4: computed 1.1.1 and 1.1.2) in an era whose stage is 2.0;
# s5 and later do not exist yet: a placement names them by their place.
NODES = """\
- {id: era-one, type: Milestone, status: pending, title: "Era", props: {kind: era, exit: "Go to 2.0?", stage_to: "2.0"}}
- {id: ms-core, type: Milestone, status: pending, title: Core}
- {id: wave-s1, type: Milestone, status: reached, title: S1, props: {kind: wave, seq: 1, release: 1.0.0, shipped_as: 1.0.0}}
- {id: wave-s2, type: Milestone, status: reached, title: S2, props: {kind: wave, seq: 2, release: 1.1.0, shipped_as: 1.1.0}}
- {id: wave-s3, type: Milestone, status: pending, title: S3, props: {kind: wave, seq: 3}}
- {id: wave-s4, type: Milestone, status: pending, title: S4, props: {kind: wave, seq: 4}}
- {id: wi-pin, type: WorkItem, status: todo, title: P, props: {wave_planned: "s4 (Ada, 2030-01-02, adr-2030-01-02-x)"}}
- {id: wi-rel-after, type: WorkItem, status: todo, title: R, props: {wave_planned: "the wave after 1.1.0 (Ada)"}}
- {id: wi-second, type: WorkItem, status: todo, title: S, props: {wave_planned: "the second wave after 1.1.0"}}
- {id: wi-stale, type: WorkItem, status: todo, title: St, props: {wave_planned: "the wave after 1.0.0 (Ada)"}}
- {id: wi-choice, type: WorkItem, status: todo, title: C, props: {wave_planned: "s5 or the next"}}
- {id: wi-split, type: WorkItem, status: todo, title: Sp, props: {wave_planned: "S1-S2 in s4 (1.1.2), S3 in s5"}}
- {id: wi-own, type: WorkItem, status: todo, title: O, props: {wave_planned: "s5, its own lot beside wi-pin's (Q-1)"}}
- {id: wi-after, type: WorkItem, status: todo, title: A,
   props: {wave_planned: "unplaced: after wi-pin and wi-own, placed at a wave's composition"}}
- {id: wi-trigger, type: WorkItem, status: todo, title: T, props: {wave_planned: "unplaced: after calibration (spec-x 8, S8)"}}
- {id: wi-paths, type: WorkItem, status: todo, title: Pa,
   props: {wave_planned: "s4, round 2 (roadmap docs/specs/2030-01-01-roadmap-s8-s12.md)"}}
- {id: wi-stage, type: WorkItem, status: todo, title: Sg, props: {wave_planned: "s6, before the 2.0 freeze (Q-2)"}}
- {id: wi-post, type: WorkItem, status: todo, title: Po, props: {wave_planned: "after 2.0, s7 (Q-2)"}}
- {id: wi-beside, type: WorkItem, status: todo, title: B,
   props: {wave_planned: "after 2.0 (Q-3); its slices wi-pin and wi-own in s4"}}
- {id: wi-norel, type: WorkItem, status: todo, title: N, props: {wave: "0.9.9 (was M, Ada)"}}
- {id: wi-prose, type: WorkItem, status: todo, title: Pr, props: {wave_fit: "somewhere nice"}}
- {id: wi-owner, type: WorkItem, status: todo, title: Ow, props: {track: "owner (out of waves, Ada 2030-01-01)"}}
- {id: wi-later, type: WorkItem, status: todo, title: L,
   props: {decided_2030_01_01: "Ada, 2030-01-01 (Q-4, ddr-2030-01-01-q4): later; nothing yet"}}
- {id: wi-later-not, type: WorkItem, status: todo, title: Ln,
   props: {decided_2030_01_01: "Ada (Q-5): the file route now; later a collector"}}
- {id: wi-decided, type: WorkItem, status: todo, title: D,
   props: {decided_2030_01_03_q6: "Ada (Q-6): in s5, before 2.0", decided_2030_01_01: "Ada: in s9"}}
- {id: wi-decided-text, type: WorkItem, status: todo, title: Dt,
   props: {wave_planned: "after 2.0", decided_2030_01_02: "Ada: its engine-free slices in s4"}}
- {id: wi-soft, type: WorkItem, status: todo, title: So, props: {after_1_0: "wi-pin (was a depends_on until 2030-01-01)"}}
- {id: wi-composed, type: WorkItem, status: todo, title: Co, props: {wave_planned: "s4, round 1, after wi-pin"}}
- {id: wi-conflict, type: WorkItem, status: todo, title: Cf, props: {wave_planned: "s4", wave_fit: "engine, s5"}}
- {id: wi-proposed, type: WorkItem, status: todo, title: Pp,
   props: {planned_wave: "s4 (proposed, the coordinator places it)"}}
- {id: wi-place, type: WorkItem, status: todo, title: Pl,
   props: {place: "v1; wave s5; after wi-pin; with wi-own; own-lot; round 1; proposed", wave_planned: "s9"}}
- {id: wi-place-bad, type: WorkItem, status: todo, title: Pb, props: {place: "wave s5; frobnicate; with wi-nobody"}}
- {id: wi-place-v2, type: WorkItem, status: todo, title: P2, props: {place: "v2; wave s5", wave_planned: "s4"}}
- {id: wi-place-out, type: WorkItem, status: todo, title: Pt, props: {place: "out trigger: after the pilot"}}
- {id: wi-place-stage, type: WorkItem, status: todo, title: Ps, props: {place: "wave s4 or s5; before 2.0; latest s6"}}
- {id: wi-closed, type: WorkItem, status: done, title: Done, props: {wave_planned: "s4"}}
- {id: wi-none, type: WorkItem, status: todo, title: None}
"""

EDGES = """\
- {from: ms-core, to: era-one, type: part_of}
- {from: wave-s1, to: ms-core, type: part_of}
- {from: wave-s2, to: ms-core, type: part_of}
- {from: wave-s3, to: ms-core, type: part_of}
- {from: wave-s4, to: ms-core, type: part_of}
- {from: wi-composed, to: wave-s3, type: part_of}
"""


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    _write(r / "notes" / "graph", NODES, EDGES)
    return r


def _plan(root):
    return waves.load(root / "notes" / "graph", root)


@pytest.mark.parametrize("nid, status, canonical", [
    ("wi-pin", "pinned", "wave s4"),
    ("wi-rel-after", "pinned", "wave s3"),            # the wave after the one 1.1.0 shipped
    ("wi-second", "pinned", "wave s4"),
    ("wi-stale", "free", "unplaced"),                 # s2 is reached: stale, listed
    ("wi-choice", "choice", "wave s5 or s6"),
    ("wi-split", "choice", "wave s4 or s5"),          # S1-S2 are slices, not waves; two waves named: a question
    ("wi-own", "pinned", "wave s5; with wi-pin; own-lot"),
    ("wi-after", "constrained", "after wi-pin, wi-own"),
    ("wi-trigger", "out", "out trigger: after calibration"),
    ("wi-paths", "pinned", "wave s4; round 2"),       # roadmap-s8-s12 in a path names no wave
    ("wi-stage", "pinned", "wave s6; before 2.0"),
    ("wi-post", "pinned", "wave s7; after 2.0"),
    ("wi-beside", "constrained", "after 2.0"),        # « in s4 » speaks of its slices
    ("wi-norel", "unparsed", ""),
    ("wi-prose", "unparsed", ""),
    ("wi-owner", "out", "out owner"),
    ("wi-later", "out", "out later"),
    ("wi-later-not", "none", ""),                     # « ; later a collector » is no « later » decision
    ("wi-decided", "pinned", "wave s5; before 2.0"),  # the newest answer first: s5, then s9 is a conflict
    ("wi-decided-text", "constrained", "after 2.0"),  # an answer's wave beside a placement text is not read
    ("wi-soft", "free", "after wi-pin past 1.0"),
    ("wi-composed", "composed", "wave s3; after wi-pin; round 1"),
    ("wi-conflict", "pinned", "wave s4"),
    ("wi-proposed", "pinned", "wave s4; proposed"),
    ("wi-place", "pinned", "wave s5; after wi-pin; with wi-own; own-lot; round 1; proposed"),
    ("wi-place-bad", "pinned", "wave s5"),
    ("wi-place-v2", "unparsed", ""),
    ("wi-place-out", "out", "out trigger: after the pilot"),
    ("wi-place-stage", "choice", "wave s4 or s5; latest s6; before 2.0"),
    ("wi-none", "none", ""),
])
def test_each_placement_resolves_to_its_status_and_props_place(root, nid, status, canonical):
    p = placement.placements(_plan(root))[nid]
    assert (p.status, p.canonical()) == (status, canonical), p


def test_what_cannot_be_honoured_is_said(root):
    pls = placement.placements(_plan(root))
    assert "wi-closed" not in pls   # done: not a candidate
    assert pls["wi-stale"].stale == ("wave_planned: s2 (reached)",)
    assert "wave: names no wave: 0.9.9" in pls["wi-norel"].notes
    assert pls["wi-split"].conflicts and "several waves (s4, s5)" in pls["wi-split"].conflicts[0]
    assert pls["wi-conflict"].conflicts == ("wave_fit names s5, wave_planned s4: wave_planned is read",)
    assert pls["wi-decided"].conflicts == ("decided_2030_01_01 names s9, decided_2030_01_03_q6 s5: "
                                           "decided_2030_01_03_q6 is read",)
    assert "not read as this item's" in " ".join(pls["wi-beside"].notes)
    assert pls["wi-composed"].conflicts == () and pls["wi-composed"].wave == "wave-s3"   # its text is history
    assert pls["wi-place-v2"].notes and "v2 is written by a newer brain" in pls["wi-place-v2"].notes[0]
    assert pls["wi-stage"].era == "era-one" and pls["wi-post"].era == "era-one"
    assert pls["wi-proposed"].soft and pls["wi-place"].soft
    assert pls["wi-trigger"].why == "after calibration"
    qs = [q for p in pls.values() for q in p.questions()]
    assert any(q.startswith("wi-choice: a choice of waves, s5 or s6") for q in qs)
    assert any(q.startswith("wi-norel: wave: names no wave: 0.9.9") for q in qs)
    assert not any(q.startswith("wi-composed") for q in qs)


def test_props_place_is_authoritative_and_its_problems_are_warnings(root):
    plan = _plan(root)
    p = placement.placements(plan)["wi-place"]
    assert p.source == "place" and p.texts == (("place", "v1; wave s5; after wi-pin; with wi-own; own-lot; round 1; "
                                                          "proposed"),)   # wave_planned's s9 not read
    assert p.constraints() == [("pin", "wi-place", 5), ("after", "wi-place", "wi-pin"),
                               ("together", "wi-place", "wi-own"), ("own_lot", "wi-place")]
    warns = placement.warnings(plan)
    assert "wi-place-bad: place: unknown clause 'frobnicate'" in warns
    assert "wi-place-bad: place: names no item: wi-nobody" in warns
    assert any(w.startswith("wi-place-v2: props.place v2") for w in warns)
    assert not any(w.startswith("wi-place:") for w in warns)


def test_the_canonical_form_reads_back_the_same(root):
    plan = _plan(root)
    pls = placement.placements(plan)
    fields = ("pin", "choice", "earliest", "latest", "before", "after_stage", "after", "soft_after", "together",
              "own_lot", "round", "soft", "out", "why")
    for nid, p in pls.items():
        if p.status in ("composed", "none", "unparsed") or not p.canonical():
            continue
        node = dict(plan.nodes[nid])
        node["props"] = {"place": p.canonical()}
        again = waves.build({**plan.nodes, nid: node}, plan.edges)
        q = placement.placements(again, [nid])[nid]
        assert {f: getattr(q, f) for f in fields} == {f: getattr(p, f) for f in fields}, nid
        assert not [n for n in q.notes if "unknown clause" in n], nid


def test_read_text_ignores_provenance_and_slices():
    items = frozenset({"wi-a", "wi-b"})
    rd = placement.read_text("S1-S3 in s9 (0.7.0; roadmap-s8-s12.md), S6 later", items)
    assert [r.value for r in rd.pins] == ["9"] and rd.out == ""
    rd = placement.read_text("after the schema, with the search", items)
    assert rd.after == [] and rd.together == [] and rd.triggers == ["after the schema"]
    rd = placement.read_text("after wi-a, wi-b and wi-c", items)
    assert rd.after == ["wi-a", "wi-b"] and rd.notes == ["names no item: wi-c"]
    assert placement.read_text("owner (out of waves)", mode="track").out == "owner"
    assert placement.read_text("the owner decides", mode="track").out == ""
    rd = placement.read_text("Ada (Q-1, 2030-01-01): built before 1.0, v0.7.0 shipped", mode="decided")
    assert rd.before == ["1.0"] and rd.pins == []   # a release in an answer is a fact, not a wave


def test_brain_wave_placements_text_and_json(root, capsys):
    base = ["--root", str(root), "wave", "placements"]
    assert cli.main(base) == 0
    out = capsys.readouterr().out
    assert out.startswith("placements of 30 open item(s): 28 with a placement, 2 without")
    assert "composed (1):\n  wave-s3: wi-composed" in out
    assert "  wi-own: wave s5; with wi-pin; own-lot  (wave_planned)" in out
    assert "    wave: 0.9.9 (was M, Ada)" in out   # an unparsed item shows its text
    assert "questions (" in out and "wi-none" not in out
    assert cli.main(base + ["--all"]) == 0
    assert "  wi-none" in capsys.readouterr().out
    assert cli.main(base + ["--json", "wi-pin", "wi-choice"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["format"] == 1 and rep["place_v"] == 1
    assert [i["id"] for i in rep["items"]] == ["wi-choice", "wi-pin"]
    assert rep["counts"]["pinned"] == 1 and rep["counts"]["choice"] == 1
    assert rep["items"][1]["pin"] == 4 and rep["items"][1]["canonical"] == "wave s4"
    assert cli.main(base + ["wi-nothing"]) == 1
    assert "not a work item: wi-nothing" in capsys.readouterr().err


def test_brain_check_warns_on_a_malformed_props_place(root, capsys):
    cli.main(["--root", str(root), "check"])
    out = capsys.readouterr().out
    assert "warning: plan: wi-place-bad: place: unknown clause 'frobnicate'" in out
