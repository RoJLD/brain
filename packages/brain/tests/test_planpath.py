"""wi-brain-milestone-order: the order of the milestones (brain.planpath, cockpit.milestone_layers; spec-brain-cockpit-
ux2 §4.3.3, UX-12; spec-brain-plan-views §8, S7): the arcs derived from the items' dependencies and weighted by their
pairs, a declared depends_on between two milestones winning, the mutual waits as knots, the ranks, the longest chain of
p50 work; ``brain milestone path [--check] [--json]`` and the text twin ``brain tui --once --tab milestones --view
path``."""

import json

import pytest

from brain import cli, cockpit, forecast, planpath, resume

# a -> b -> c, and a -> c over a rank; d <-> e a mutual wait; h before g declared, g -> h derived and overruled;
# f's only pair is done (history only); a wave's and an era's items never make an arc; k has no arc
NODES = """
- {id: era-demo-one, type: Milestone, status: pending, title: "Era", props: {kind: era}}
- {id: wave-s1, type: Milestone, status: pending, title: "Wave", props: {kind: wave}}
- {id: ms-demo-a, type: Milestone, status: pending, title: "A"}
- {id: ms-demo-b, type: Milestone, status: pending, title: "B"}
- {id: ms-demo-c, type: Milestone, status: pending, title: "C"}
- {id: ms-demo-d, type: Milestone, status: pending, title: "D"}
- {id: ms-demo-e, type: Milestone, status: pending, title: "E"}
- {id: ms-demo-f, type: Milestone, status: reached, title: "F", props: {reached: "2026-11-10"}}
- {id: ms-demo-g, type: Milestone, status: pending, title: "G"}
- {id: ms-demo-h, type: Milestone, status: pending, title: "H"}
- {id: ms-demo-k, type: Milestone, status: pending, title: "K, alone"}
- {id: ms-demo-gone, type: Milestone, status: dropped, title: "Dropped"}
- {id: wi-a1, type: WorkItem, status: todo, title: "a1"}
- {id: wi-a2, type: WorkItem, status: done, title: "a2"}
- {id: wi-b1, type: WorkItem, status: doing, title: "b1"}
- {id: wi-b2, type: WorkItem, status: todo, title: "b2"}
- {id: wi-c1, type: WorkItem, status: todo, title: "c1"}
- {id: wi-c2, type: WorkItem, status: blocked, title: "c2"}
- {id: wi-d1, type: WorkItem, status: todo, title: "d1"}
- {id: wi-d2, type: WorkItem, status: todo, title: "d2"}
- {id: wi-e1, type: WorkItem, status: todo, title: "e1"}
- {id: wi-e2, type: WorkItem, status: todo, title: "e2"}
- {id: wi-f1, type: WorkItem, status: done, title: "f1"}
- {id: wi-g1, type: WorkItem, status: todo, title: "g1"}
- {id: wi-h1, type: WorkItem, status: todo, title: "h1"}
- {id: wi-k1, type: WorkItem, status: todo, title: "k1"}
- {id: wi-w1, type: WorkItem, status: todo, title: "in a wave alone"}
- {id: wi-x1, type: WorkItem, status: dropped, title: "dropped"}
"""
EDGES = """
- {from: wi-a1, to: ms-demo-a, type: part_of}
- {from: wi-a2, to: ms-demo-a, type: part_of}
- {from: wi-b1, to: ms-demo-b, type: part_of}
- {from: wi-b2, to: ms-demo-b, type: part_of}
- {from: wi-c1, to: ms-demo-c, type: part_of}
- {from: wi-c2, to: ms-demo-c, type: part_of}
- {from: wi-d1, to: ms-demo-d, type: part_of}
- {from: wi-d2, to: ms-demo-d, type: part_of}
- {from: wi-e1, to: ms-demo-e, type: part_of}
- {from: wi-e2, to: ms-demo-e, type: part_of}
- {from: wi-f1, to: ms-demo-f, type: part_of}
- {from: wi-g1, to: ms-demo-g, type: part_of}
- {from: wi-h1, to: ms-demo-h, type: part_of}
- {from: wi-k1, to: ms-demo-k, type: part_of}
- {from: wi-w1, to: wave-s1, type: part_of}
- {from: wi-a1, to: wave-s1, type: part_of}
- {from: wi-x1, to: ms-demo-b, type: part_of}
- {from: ms-demo-a, to: era-demo-one, type: part_of}
- {from: wi-b1, to: wi-a1, type: depends_on}
- {from: wi-b2, to: wi-a1, type: depends_on}
- {from: wi-c1, to: wi-b1, type: depends_on}
- {from: wi-c2, to: wi-a1, type: depends_on}
- {from: wi-c2, to: wi-a2, type: depends_on}
- {from: wi-d1, to: wi-e1, type: depends_on}
- {from: wi-e2, to: wi-d2, type: depends_on}
- {from: wi-f1, to: wi-a2, type: depends_on}
- {from: wi-h1, to: wi-g1, type: depends_on}
- {from: ms-demo-g, to: ms-demo-h, type: depends_on}
- {from: wi-w1, to: wi-a1, type: depends_on}
- {from: wi-x1, to: wi-a1, type: depends_on}
"""


def _hours(p50, h):
    return {"dates": {"p10": p50, "p50": p50, "p80": p50, "p90": p50}, "shown": "range",
            "work": {"hours": {"p10": h, "p50": h, "p80": h, "p90": h}}}


FC = {"forecast": 1, "project": "demo", "as_of": "2026-11-24T08:00+00:00",
      "milestones": [{"id": "ms-demo-a", **_hours("2026-11-28", 2.0)}, {"id": "ms-demo-b", **_hours("2026-12-02", 1.0)},
                     {"id": "ms-demo-c", **_hours("2026-12-05", 1.5)}, {"id": "ms-demo-d", **_hours("2026-12-09", 9.0)},
                     {"id": "ms-demo-e", **_hours("2026-12-01", 1.0)},
                     {"id": "ms-demo-g", "shown": "undated", "held": "", "undated": ["wi-g1"]}]}


@pytest.fixture
def st(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(NODES)
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(EDGES)
    return resume.Store.load(store)


def _arc(lay, a, b):
    return next((x for x in lay["arcs"] if (x["from"], x["to"]) == (f"ms-demo-{a}", f"ms-demo-{b}")), None)


def _node(lay, nid):
    return next(n for n in lay["nodes"] if n["id"] == nid)


def test_the_arcs_come_from_the_items_live_waits_weighted_by_their_pairs(st):
    lay = planpath.layers(st, FC, "demo")
    assert lay["v"] == planpath.V == 1 and lay["history"] is False and lay["forecast"] is True
    ab = _arc(lay, "a", "b")
    assert ab["pairs"] == 2 and ab["items"] == [["wi-b1", "wi-a1"], ["wi-b2", "wi-a1"]] and not ab["declared"]
    assert _arc(lay, "a", "c")["pairs"] == 1   # c2 waits on a1 (open) and on a2 (done: no wait)
    assert _arc(lay, "a", "f") is None   # f1 done: its pair waits no more
    ends = {(x["from"], x["to"]) for x in lay["arcs"]}
    assert not any("wave" in a or "era" in a or "wave" in b or "era" in b for a, b in ends)   # off the path
    assert "ms-demo-gone" not in {m["id"] for m in lay["milestones"]}
    assert lay["unlinked"] == ["ms-demo-f", "ms-demo-k", "ms-x"]   # ms-x: the fixture store's


def test_history_counts_the_done_pairs_too(st):
    lay = planpath.layers(st, FC, "demo", history=True)
    assert _arc(lay, "a", "f")["pairs"] == 1 and _arc(lay, "a", "c")["pairs"] == 2
    assert lay["unlinked"] == ["ms-demo-k", "ms-x"] and lay["history"] is True
    assert "every pair, the done ones too" in planpath.heading(lay)


def test_a_declared_order_wins_over_a_derived_arc_the_other_way(st):
    lay = planpath.layers(st, FC, "demo")
    hg = _arc(lay, "h", "g")
    assert hg["declared"] and hg["pairs"] == 0
    assert _arc(lay, "g", "h") is None
    assert [(o["from"], o["to"], o["by"]) for o in lay["overruled"]] == [
        ("ms-demo-g", "ms-demo-h", "ms-demo-g depends_on ms-demo-h")]
    assert not any("ms-demo-g" in k["members"] for k in lay["knots"])
    assert _node(lay, "ms-demo-g")["rank"] == 2 and _node(lay, "ms-demo-h")["rank"] == 1


def test_a_mutual_wait_is_a_knot_with_its_pairs_each_way(st):
    lay = planpath.layers(st, FC, "demo")
    (k,) = lay["knots"]
    assert k["id"] == "knot:ms-demo-d+ms-demo-e" and k["members"] == ["ms-demo-d", "ms-demo-e"] and k["rank"] == 1
    assert {(a["from"], a["to"], a["pairs"]) for a in k["arcs"]} == {("ms-demo-d", "ms-demo-e", 1),
                                                                      ("ms-demo-e", "ms-demo-d", 1)}
    node = _node(lay, k["id"])
    assert node["kind"] == "knot" and node["done"] == 0 and node["items"] == 4 and node["p50"] == "2026-12-09"
    assert node["hours"] == 10.0
    text = "\n".join(planpath.problems(lay))
    assert "knot d ⇄ e: a mutual wait (rank 1)" in text and "wi-d1 waits on wi-e1" in text
    assert "brain item link ms-demo-e depends_on ms-demo-d" in text


def test_the_ranks_place_a_milestone_after_its_longest_chain(st):
    lay = planpath.layers(st, FC, "demo")
    assert lay["ranks"][0] == ["ms-demo-a", "knot:ms-demo-d+ms-demo-e", "ms-demo-h"]
    c = _node(lay, "ms-demo-c")
    assert c["rank"] == 3 and c["before"] == ["ms-demo-a", "ms-demo-b"] and c["after"] == ["ms-demo-a"]
    assert _node(lay, "ms-demo-a")["after_this"] == ["ms-demo-b", "ms-demo-c"]
    assert [len(r) for r in lay["ranks"]] == [3, 2, 1]


def test_the_chain_is_the_longest_by_p50_work_else_by_count(st):
    lay = planpath.layers(st, FC, "demo")
    assert lay["chain"] == ["knot:ms-demo-d+ms-demo-e"] and lay["chain_hours"] == 10.0   # 10 h against a-b-c's 4.5
    fc = {**FC, "milestones": [m for m in FC["milestones"] if m["id"] not in ("ms-demo-d", "ms-demo-e")]}
    lay = planpath.layers(st, fc, "demo")
    assert lay["chain"] == ["ms-demo-a", "ms-demo-b", "ms-demo-c"] and lay["chain_hours"] == 4.5
    lay = planpath.layers(st, None, "demo")   # no forecast: the longest chain by its milestones
    assert lay["chain"] == ["ms-demo-a", "ms-demo-b", "ms-demo-c"] and lay["chain_hours"] is None
    assert lay["forecast"] is False and lay["as_of"] is None


def test_a_forecast_that_answers_garbage_reads_as_none(st):
    fc = {"milestones": [{"id": "ms-demo-a", "dates": None, "work": {"hours": {"p50": "two"}}}, {"x": 1}, "junk"]}
    lay = planpath.layers(st, {**fc, "milestones": fc["milestones"][:2]}, "demo")
    a = next(m for m in lay["milestones"] if m["id"] == "ms-demo-a")
    assert a["p50"] == "" and a["hours"] is None and lay["chain"] == ["ms-demo-a", "ms-demo-b", "ms-demo-c"]


def test_tarjan_finds_a_longer_cycle_and_a_declared_order_both_ways_is_a_knot(st, store):
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write("- {from: wi-a1, to: wi-c1, type: depends_on}\n"   # c before a: a -> b -> c -> a
                "- {from: ms-demo-h, to: ms-demo-g, type: depends_on}\n")   # g before h too: declared both ways
    lay = planpath.layers(resume.Store.load(store), FC, "demo")
    members = sorted(tuple(k["members"]) for k in lay["knots"])
    assert members == [("ms-demo-a", "ms-demo-b", "ms-demo-c"), ("ms-demo-d", "ms-demo-e"),
                       ("ms-demo-g", "ms-demo-h")]
    gh = next(k for k in lay["knots"] if "ms-demo-g" in k["members"])
    assert gh["declared"] and "a declared order is part of it" in "\n".join(planpath.knot_lines(gh, "demo"))
    assert lay["overruled"] == []


def test_the_lanes_from_120_columns(st):
    lay = planpath.layers(st, FC, "demo")
    wide = planpath.text(lay, 120, plain=False)
    blob = "\n".join(wide)
    assert wide[0].startswith("rank 1") and "rank 3" in wide[0]
    assert "─▶" in wide[1] and "a 1/2" in wide[1] and "◆ ⟦d ⇄ e⟧ 0/4" in blob
    assert "↳ after a" in blob and "p50 Nov 28" in blob and "g 0/1" in blob and "undated" in blob
    assert "\nno arc: ✓ f 1/1 · k 0/1" in blob and "\n1 mutual wait(s) to settle: ⟦d ⇄ e⟧" in blob
    assert "\n1 derived arc(s) overruled" in blob
    assert max(len(x) for x in wide[:-4]) <= 120   # the drawing fits; the tail's lines are not cut


def test_the_tree_under_120_columns(st):
    lay = planpath.layers(st, FC, "demo")
    narrow = planpath.text(lay, 100, plain=False)
    assert narrow[0].startswith("├── a 1/2") and "↗ c" in "\n".join(narrow)   # c under a and under b
    assert planpath.grid(lay, 100, columns=130)["mode"] == "lanes"   # the screen's columns decide
    assert planpath.grid(lay, 130, columns=100)["mode"] == "tree"


def test_the_legacy_console_gets_words(st, monkeypatch):
    monkeypatch.setenv("TERM", "linux")
    lay = planpath.layers(st, FC, "demo")
    out = "\n".join(planpath.text(lay, 120))
    assert "->" in out and "[d <-> e]" in out and "after a" in out and "─" not in out and "⟦" not in out
    tree = "\n".join(planpath.text(lay, 100))
    assert "`-- " in tree and "^ c" in tree


def test_a_knot_too_large_for_its_cell_shows_its_count():
    x = {"kind": "knot", "name": " ⇄ ".join(f"milestone-{i}" for i in range(9))}
    assert planpath._name(x, False, 20) == "⟦9 milestones⟧"
    assert planpath._name(x, False) .startswith("⟦milestone-0 ⇄ milestone-1")


def test_an_empty_graph_says_so(store):
    lay = planpath.layers(resume.Store.load(store), None, "demo")
    assert lay["ranks"] == [] and lay["chain"] == [] and lay["unlinked"] == ["ms-x"]
    out = planpath.text(lay, 120)
    assert "no arc between two milestones" in out[0] and "no forecast yet: brain forecast" in out[-1]


def test_the_cockpit_s_plan_panel_carries_the_layers(st):
    lay = cockpit.milestone_layers(st, FC, "demo")
    assert lay == planpath.layers(st, FC, "demo")
    panel = {"projects": [{"project": "demo", "path": lay}]}
    assert cockpit.heading("path", panel).startswith("Milestones · Path · 10 milestone(s), 6 arc(s) from the live")
    assert "path" in cockpit.TABS["milestones"]["views"] and cockpit.FRAMES["path"] == "plan"
    assert cockpit.plan_view("path") and cockpit.VIEW_LABELS["path"]["fr"] == "Chemin" and "path" in cockpit.HELP
    text = planpath.lines(panel, 120)
    assert text[0] == "Milestones · Path" and text[1].startswith("  10 milestone(s)") and text[2].startswith("  rank 1")
    two = planpath.lines({"projects": [{"project": "demo", "path": lay}, {"project": "acme", "error": "gone"}]}, 120)
    assert "  demo: 10 milestone(s)" in two[1] and two[-1] == "  acme: error: gone"
    assert planpath.lines(None) == ["Milestones · Path", "  no project read yet"]


def _root(st, store, fc=FC):
    root = store.parents[1]
    forecast.folder(root.name).mkdir(parents=True, exist_ok=True)
    (forecast.folder(root.name) / "latest.json").write_text(json.dumps(fc), encoding="utf-8")
    return root


def test_brain_milestone_path_prints_checks_and_gives_its_json(st, store, capsys):
    root = _root(st, store)
    assert cli.main(["--root", str(root), "milestone", "path", "--width", "120"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"Milestones · Path · {root.name}: 10 milestone(s)") and "rank 1" in out
    assert cli.main(["--root", str(root), "milestone", "path", "--check"]) == 1
    out = capsys.readouterr().out
    assert "knot demo-d ⇄ demo-e: a mutual wait" in out   # the project is the root folder's name: ms- goes alone
    assert cli.main(["--root", str(root), "milestone", "path", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["v"] == 1 and set(data) >= {"v", "project", "history", "as_of", "forecast", "milestones", "arcs",
                                            "overruled", "knots", "nodes", "ranks", "chain", "chain_hours",
                                            "unlinked"}
    assert cli.main(["--root", str(root), "milestone", "path", "--json", "--history"]) == 0
    assert json.loads(capsys.readouterr().out)["history"] is True
    assert cli.main(["--root", str(root), "milestone", "path", "--width", "90"]) == 0
    assert "├── " in capsys.readouterr().out


def test_the_check_passes_once_the_knot_is_settled_by_a_declared_order(st, store, capsys):
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write("- {from: ms-demo-e, to: ms-demo-d, type: depends_on}\n")
    root = _root(st, store)
    assert cli.main(["--root", str(root), "milestone", "path", "--check"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("path: no mutual wait (10 milestone(s)") and "0 mutual wait(s)" in out
    lay = planpath.layers(resume.Store.load(store), FC, "demo")
    assert {(o["from"], o["to"]) for o in lay["overruled"]} >= {("ms-demo-e", "ms-demo-d")}


def test_brain_tui_once_prints_the_path_view(st, store, capsys):
    root = _root(st, store)
    assert cli.main(["--root", str(root), "tui", "--once", "--quick", "--tab", "milestones", "--view", "path"]) == 0
    out = capsys.readouterr().out
    assert "Milestones · Path" in out and "⟦demo-d ⇄ demo-e⟧" in out and "Milestones (" not in out and "· Tree ·" not in out
    assert cli.main(["--root", str(root), "tui", "--once", "--quick", "--tab", "milestones"]) == 0
    assert "Milestones · Path" not in capsys.readouterr().out   # the tab's list alone
    assert cli.main(["--root", str(root), "tui", "--json", "--quick"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["panels"]["plan"]["projects"][0]["path"]["v"] == 1
