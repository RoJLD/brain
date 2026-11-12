"""wi-brain-prioritization: brain next ranks the frontier by the owner's priority, the owner's order, then value over
effort (brain.ranking), its quick wins first, --explain showing each score's parts."""

import json

from brain import cli, forecast, ranking


def _node(nid, typ="WorkItem", status="todo", **props):
    return {"id": nid, "type": typ, "status": status, "title": nid, **({"props": props} if props else {})}


NODES = {n["id"]: n for n in [
    _node("feat-hi", "Feature", "have", value="high"),
    _node("feat-lo", "Feature", "have", value="low"),
    _node("ms-road", "Milestone", "pending"),
    _node("wave-1.0.0", "Milestone", "pending", kind="wave", release="1.0.0"),
    _node("wi-quick", priority="P1", size="S", size_reason="a flag"),          # 1 + 3 + 1 = 5 / 0.3 h
    _node("wi-big", priority="P1", size="XL", size_reason="many modules"),    # 1 + 3 + 1 = 5 / 4 h
    _node("wi-plain", priority="P1"),                                          # 1 / 0.8 h (no size: M)
    _node("wi-ordered", priority="P1", order=1, size="XL", size_reason="x"),  # the owner's order wins over the score
    _node("wi-proposed", priority_proposed="P1", size="S", size_reason="x"),   # after every confirmed P1
    _node("wi-p0", priority="P0", size="L", size_reason="x"),
    _node("wi-owned", priority="P2", size="S", size_reason="x", value="high", value_reason="the pilot needs it"),
    _node("wi-waits", priority="P3"),                                          # depends on wi-plain
    _node("wi-done", status="done"),                                           # depends on wi-plain: closed, ignored
]}
EDGES = [
    {"from": "wi-quick", "to": "feat-hi", "type": "delivers"},
    {"from": "wi-quick", "to": "ms-road", "type": "part_of"},
    {"from": "wi-big", "to": "feat-hi", "type": "delivers"},
    {"from": "wi-big", "to": "ms-road", "type": "part_of"},
    {"from": "wi-plain", "to": "wave-1.0.0", "type": "part_of"},              # a wave is a timebox, not a milestone
    {"from": "wi-plain", "to": "feat-lo", "type": "depends_on"},             # not delivers: no feature value
    {"from": "wi-waits", "to": "wi-plain", "type": "depends_on"},
    {"from": "wi-done", "to": "wi-plain", "type": "depends_on"},
]


def test_the_value_is_derived_from_the_graph_and_the_effort_from_the_size():
    r = ranking.Ranker(NODES, EDGES)
    quick = r.score("wi-quick")
    assert quick.parts == {"base": 1.0, "features": 3.0, "milestone": 1.0, "unblocks": 0.0}
    assert (quick.value, quick.hours, quick.score, quick.level, quick.quick_win) == (5.0, 0.3, 16.6667, "high", True)
    big = r.score("wi-big")
    assert (big.value, big.hours, big.score, big.quick_win) == (5.0, 4.0, 1.25, False)   # high, but not small
    plain = r.score("wi-plain")
    assert plain.parts == {"base": 1.0, "features": 0.0, "milestone": 0.0, "unblocks": 0.5}   # one open dependent
    assert (plain.size, plain.hours, plain.level) == ("", 0.8, "low")
    assert plain.explain() == "score 1.88 = value 1.5 (base 1 + unblocks 0.5) / 0.8 h (M?, no size)"


def test_the_owners_value_wins_and_is_counted():
    r = ranking.Ranker(NODES, EDGES)
    owned = r.score("wi-owned")
    assert (owned.override, owned.value, owned.level, owned.quick_win) == ("high", 5.0, "high", True)
    assert owned.explain() == "score 16.67 = value 5 (high, the owner's (derived 1)) / 0.3 h (S)"
    assert r.overrides(list(NODES)) == ["wi-owned"]
    assert ranking.Ranker({"x": _node("x", value="huge")}, []).score("x").override == ""   # off the scale: derived


def test_the_rank_is_priority_then_order_then_score():
    r = ranking.Ranker(NODES, EDGES)
    items = [n for n, v in NODES.items() if v["type"] == "WorkItem" and v["status"] == "todo"]
    assert r.ranked(items) == ["wi-p0", "wi-ordered", "wi-quick", "wi-plain", "wi-big", "wi-proposed", "wi-owned",
                               "wi-waits"]
    assert ranking.order_of(_node("x", order="health first")) is None   # a text order is no order
    assert ranking.order_of(_node("x", order=True)) is None


def test_forecast_shares_the_written_score():
    assert forecast.SCORE is ranking.SCORE


STORE = """\
- {id: wave-1.0.0, type: Milestone, status: pending, title: "Wave 1.0.0", props: {kind: wave, release: 1.0.0}}
- {id: feat-hi, type: Feature, status: have, title: "Hi", props: {value: high}}
- {id: ms-road, type: Milestone, status: pending, title: "Road"}
- {id: wi-slow, type: WorkItem, status: todo, title: "Slow", props: {priority: P1, size: XL, size_reason: x}}
- {id: wi-fast, type: WorkItem, status: todo, title: "Fast", props: {priority: P1, size: S, size_reason: x}}
"""
EDGES_YAML = """\
- {from: wi-slow, to: wave-1.0.0, type: part_of}
- {from: wi-fast, to: wave-1.0.0, type: part_of}
- {from: wi-fast, to: feat-hi, type: delivers}
- {from: wi-fast, to: ms-road, type: part_of}
"""


def test_brain_next_lists_quick_wins_first_and_explains(store, capsys):
    root = store.parents[1]
    (store / "nodes" / "plan.yaml").write_text(STORE, encoding="utf-8")
    (store / "edges" / "plan.yaml").write_text(EDGES_YAML, encoding="utf-8")
    assert cli.main(["--root", str(root), "next", "--explain"]) == 0
    out = capsys.readouterr().out
    assert "  quick wins (size S, high value), first: wi-fast" in out
    assert out.index("wi-fast [todo]") < out.index("wi-slow [todo]")
    assert "        score 16.67 = value 5 (base 1 + features 3 + milestone 1) / 0.3 h (S)" in out
    assert "        score 0.25 = value 1 (base 1) / 4 h (XL)" in out
    assert cli.main(["--root", str(root), "next"]) == 0
    assert "score " not in capsys.readouterr().out   # the parts only with --explain
    assert cli.main(["--root", str(root), "next", "--json"]) == 0
    cur = json.loads(capsys.readouterr().out)["current"]
    assert cur["quick_wins"] == ["wi-fast"] and cur["value_overrides"] == []
    assert cur["startable"][0]["rank"]["score"] == 16.6667


def test_the_cockpit_frontier_takes_the_rank_and_shows_the_parts(store):
    from brain import cockpit, resume
    (store / "nodes" / "plan.yaml").write_text(STORE, encoding="utf-8")
    (store / "edges" / "plan.yaml").write_text(EDGES_YAML, encoding="utf-8")
    rows = [r for r in cockpit.frontier_rows(resume.Store.load(store)) if r["id"] in ("wi-fast", "wi-slow")]
    assert [r["id"] for r in rows] == ["wi-fast", "wi-slow"]
    fast = {**rows[0], "project": "demo"}
    assert (fast["size"], fast["value"], fast["score"], fast["quick_win"], fast["order"]) == ("S", "high", 16.6667,
                                                                                             True, None)
    chosen = {"shown": ["Id", "Size", "Value", "Score"]}
    assert cockpit.cells("frontier", fast, chosen=chosen) == ("wi-fast", "S", "high (quick win)", "16.6667")
    by_score = sorted([{"priority": "P2", "score": 1.0}, {"priority": "P1", "score": 0.5}],
                      key=cockpit.SORT_KEYS["frontier"]["score"])
    assert [r["score"] for r in by_score] == [1.0, 0.5]
