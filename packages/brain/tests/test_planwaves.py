"""wi-brain-tui-waves: the Milestones Tree's waves axis enriched (brain.planviews; spec-brain-plan-views §3.2, S2;
VIZ-2): a pending wave's open items in its lots by round, as brain wave plan cuts them (brain.lots), each item's PR,
the wave it was carried from and the live session working on it, the carried items first, the P0/P1 filter."""

import pytest
from brain import cockpit, lots, planviews, resume, waves
from test_planviews import EDGES, FC, NODES, _find  # the fixture graph of the Tree

MORE_NODES = """
- {id: wi-x1, type: WorkItem, status: todo, title: "Edit tui_plan.py", props: {priority: P1}}
- {id: wi-x2, type: WorkItem, status: todo, title: "Fix tui_plan.py too", props: {priority: P0, pr: "RoJLD/brain#300"}}
"""
MORE_EDGES = """
- {from: wi-x1, to: wave-s2, type: part_of}
- {from: wi-x2, to: wave-s2, type: part_of}
- {from: wi-w, to: wi-a, type: depends_on}
"""
def _session(state, name, items, host_id=""):
    """A sessions panel row (as test_tui's), its report naming ``items``."""
    return {"state": state, "session_id": host_id or name, "project": "demo", "step": "", "model": "claude-opus-5-5",
            "effort": "high", "context": 1000, "budget": 600_000, "output_tokens": 10, "age_s": 30, "title": "",
            "branch": "b", "name": name, "host_id": host_id, "report": {"items": items}}


SESSIONS = {"hours": 24, "rows": [_session("running", "s8-x", ["wi-a"]), _session("ended", "old", ["wi-w"]),
                                  _session("asking", "", ["wi-x2"], "local_abcdef123456")]}


@pytest.fixture
def st(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(NODES + MORE_NODES)
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(EDGES + MORE_EDGES)
    return resume.Store.load(store)


def _wave(st, at_once=planviews.AT_ONCE):
    return _find(planviews.tree(st, FC, "waves", "demo", at_once), "demo:wave-s2")


def test_a_pending_waves_open_items_sit_in_its_lots_by_round(st):
    s2 = _wave(st)
    lot_rows = [c for c in s2["children"] if c["kind"] == "lot"]
    # wi-a unblocks wi-w (round 2); wi-x1 and wi-x2 meet on tui_plan.py: one lot, the P0 first
    assert [x["name"] for x in lot_rows] == ["round 1 · lot 1 (1)", "round 1 · lot 2 (2)", "round 1 · lot 3 (1)",
                                             "round 2 · lot 4 (1)"]
    assert [[k["id"] for k in x["children"]] for x in lot_rows] == [["wi-a"], ["wi-x2", "wi-x1"], ["wi-carry"],
                                                                    ["wi-w"]]
    assert lot_rows[1]["chain"] == "wi-x2 P0 → wi-x1 P1" and lot_rows[1]["checked"] and not lot_rows[0]["checked"]
    assert s2["children"][-1]["kind"] == "done"   # the done ones folded after the lots
    # rounds at the size in force: two lots a round
    names = [x["name"] for x in _wave(st, 2)["children"] if x["kind"] == "lot"]
    assert names == ["round 1 · lot 1 (1)", "round 1 · lot 2 (2)", "round 2 · lot 3 (1)", "round 3 · lot 4 (1)"]
    # the same lots as brain wave plan's
    pl = waves.build(st.nodes, st.edges)
    units = lots.units_of(pl, st, "wave-s2")
    found, _ = lots.lots_of(units)
    assert sorted(sorted(x.items) for x in found) == sorted(sorted(k["id"] for k in x["children"]) for x in lot_rows)


def test_a_reached_wave_and_the_thematic_axis_have_no_lots(st):
    s1 = _find(planviews.tree(st, FC, "waves", "demo"), "demo:wave-s1")
    assert not any(c["kind"] == "lot" for c in s1["children"])
    core = _find(planviews.tree(st, FC, "milestones", "demo"), "demo:ms-demo-core")
    assert not any(c["kind"] == "lot" for c in core["children"]) and "pr" not in _find([core], "demo:wi-a")


def test_an_item_shows_its_pr_the_wave_it_came_from_and_its_session(st):
    nodes = planviews.tree(st, FC, "waves", "demo")
    x2, carry = _find(nodes, "demo:wi-x2"), _find(nodes, "demo:wi-carry")
    assert x2["pr"] == "RoJLD/brain#300" and carry["carried"] == "0.1.0" and not x2["carried"]
    working = planviews.sessions_of(SESSIONS)
    assert working == {"wi-a": "s8-x", "wi-x2": "local_abcdef12"}   # live ones only; no name: the short id
    assert "PR RoJLD/brain#300  session local_abcdef12" in planviews.label(x2, 3, plain=False, working=working)
    assert "↩ 0.1.0" in planviews.label(carry, 3, plain=False)
    assert "carried from 0.1.0" in planviews.label(carry, 3, plain=True)
    lot = next(c for c in _wave(st)["children"] if c["kind"] == "lot")
    assert planviews.label(lot, 2) == "round 1 · lot 1 (1)  wi-a P2  (surface unknown: unchecked)"


def test_the_carried_items_come_first_among_their_state():
    rows = [{"state": "todo", "priority": "P0", "id": "a"}, {"state": "todo", "priority": "P2", "id": "b",
                                                              "carried": "0.1.0"},
            {"state": "doing", "priority": "P3", "id": "c"}]
    assert [r["id"] for r in sorted(rows, key=planviews._item_order)] == ["c", "b", "a"]


def test_only_keeps_the_p0_and_p1_items_and_what_holds_them(st):
    nodes = planviews.tree(st, FC, "waves", "demo")
    kept = planviews.only(nodes)
    ids = set()

    def walk(ns):
        for n in ns:
            ids.add(n["id"] or n["name"])
            walk(n["children"])
    walk(kept)
    assert {"wi-x1", "wi-x2", "wi-carry", "wi-b"} <= ids and not ids & {"wi-a", "wi-w", "wi-e"}
    assert "round 1 · lot 1 (1)" not in ids and _find(nodes, "demo:wi-a")   # the tree itself untouched
    assert planviews.only([{"kind": "item", "priority": "P1?", "children": []}])   # a proposed P1 counts


def test_only_counts_and_chains_what_each_row_still_holds(st):
    """A lot of a P0 and a P2 item reads (1) and chains the P0 alone under f; the groups count what they keep."""
    st.nodes["wi-x1"]["props"]["priority"] = "P2"
    nodes = planviews.tree(st, FC, "waves", "demo")
    lot = _find(nodes, "demo:wave-s2:lot-2")
    assert (lot["name"], lot["chain"]) == ("round 1 · lot 2 (2)", "wi-x2 P0 → wi-x1 P2")
    kept = planviews.only(nodes)
    lot = _find(kept, "demo:wave-s2:lot-2")
    assert (lot["name"], lot["chain"]) == ("round 1 · lot 2 (1)", "wi-x2 P0")
    assert planviews.label(lot) == "round 1 · lot 2 (1)  wi-x2 P0"
    assert next(n for n in nodes if n["kind"] == "group")["name"] == "(no wave)  5 open item(s)"
    assert next(n for n in kept if n["kind"] == "group")["name"] == "(no wave)  2 open item(s)"
    done = {"kind": "done", "name": "3 done", "children": [
        {"kind": "item", "priority": p, "children": []} for p in ("P1", "P2", "P3")]}
    assert planviews.only([done])[0]["name"] == "1 done"


def test_the_text_twin_and_the_cockpit_draw_the_lots_and_the_sessions(st):
    panel = {"projects": [planviews.collect(st, FC, "demo")]}
    out = "\n".join(planviews.lines(panel, "waves", 160, plain=False, working=planviews.sessions_of(SESSIONS)))
    assert "round 1 · lot 2 (2)  wi-x2 P0 → wi-x1 P1" in out and "session s8-x" in out
    snap = {"scope": "demo", "read_at": "2026-11-18T10:00:00Z", "panels": {"plan": panel, "sessions": SESSIONS}}
    text = "\n".join(cockpit.render(snap, 160, tab="milestones", view="tree", axis="waves"))
    assert "round 2 · lot 4 (1)" in text and "session local_abcdef12" in text


def test_build_reads_the_same_plan_as_load(st, store):
    built, loaded = waves.build(st.nodes, st.edges), waves.load(store)
    assert dict(built.parents) == dict(loaded.parents) and dict(built.members) == dict(loaded.members)
    assert dict(built.deps) == dict(loaded.deps) and built.waves == loaded.waves and not built.ddrs
    assert planviews.AT_ONCE == lots.AT_ONCE
