"""wi-brain-tui-plan-tree: the Milestones tab's Tree (brain.planviews; spec-brain-plan-views §3.1, §3.2, §3.6; VIZ-1,
VIZ-2): era > milestone > item and era > wave > item from the graph and the forecast's latest.json, never recomputed;
its text twin (brain tui --once --tab milestones --view tree [--axis waves]) and the cockpit's plan panel."""

import json
import re

import pytest

from brain import cli, cockpit, forecast, planviews, projects, resume

NODES = """
- {id: era-demo-one, type: Milestone, status: pending, title: "Era 1", props: {kind: era}}
- {id: ms-demo-core, type: Milestone, status: pending, title: "Core"}
- {id: ms-demo-sub, type: Milestone, status: pending, title: "Core, its part"}
- {id: ms-demo-loose, type: Milestone, status: pending, title: "No era"}
- {id: ms-demo-gone, type: Milestone, status: dropped, title: "Dropped"}
- {id: wave-s1, type: Milestone, status: reached, title: "Wave 1",
   props: {kind: wave, release: "0.1.0", reached: "2026-11-10"}}
- {id: wave-s2, type: Milestone, status: pending, title: "Wave 2", props: {kind: wave, release: "0.2.0"}}
- {id: wi-a, type: WorkItem, status: doing, title: "A", props: {priority: P2}}
- {id: wi-b, type: WorkItem, status: todo, title: "B", props: {priority: P1}}
- {id: wi-c, type: WorkItem, status: done, title: "C", props: {priority: P1, done: "2026-11-09 ok"}}
- {id: wi-d, type: WorkItem, status: dropped, title: "D"}
- {id: wi-e, type: WorkItem, status: todo, title: "E [x]", props: {priority_proposed: P3}}
- {id: wi-w, type: WorkItem, status: todo, title: "In a wave alone", props: {priority: P2}}
- {id: wi-carry, type: WorkItem, status: todo, title: "Carried", props: {priority: P1, carried_to: wave-s2}}
- {id: wi-ext, type: WorkItem, status: blocked, title: "After another project", props: {priority: P2}}
"""
EDGES = """
- {from: ms-demo-core, to: era-demo-one, type: part_of}
- {from: ms-demo-sub, to: ms-demo-core, type: part_of}
- {from: wave-s1, to: era-demo-one, type: part_of}
- {from: wave-s2, to: era-demo-one, type: part_of}
- {from: wi-a, to: ms-demo-core, type: part_of}
- {from: wi-b, to: ms-demo-sub, type: part_of}
- {from: wi-c, to: ms-demo-core, type: part_of}
- {from: wi-d, to: ms-demo-core, type: part_of}
- {from: wi-e, to: ms-demo-loose, type: part_of}
- {from: wi-a, to: wave-s2, type: part_of}
- {from: wi-c, to: wave-s1, type: part_of}
- {from: wi-w, to: wave-s2, type: part_of}
- {from: wi-carry, to: wave-s1, type: part_of}
- {from: wi-carry, to: ms-demo-core, type: part_of}
- {from: wi-ext, to: ms-demo-gone, type: part_of}
"""
FC = {"forecast": 1, "project": "demo", "as_of": "2026-11-18T08:00+00:00",
      "calibration": {"state": "uncalibrated", "judged": 1, "needed": 5},
      "milestones": [{"id": "ms-demo-core", "open": 3, "shown": "range", "gates": ["calendar 2026-12-01"],
                      "dates": {"p10": "2026-11-20", "p50": "2026-11-25", "p80": "2026-11-30", "p90": "2026-12-04"}},
                     {"id": "ms-demo-loose", "open": 1, "shown": "undated", "dates": None, "held": "",
                      "undated": ["wi-e"]}],
      "items": [{"id": "wi-a", "days": {"p10": 1, "p50": 2, "p80": 3, "p90": 4}, "ddr": ["ddr-x"], "action": [],
                 "dates": {"p10": "2026-11-19", "p50": "2026-11-20", "p80": "2026-11-21", "p90": "2026-11-22"}},
                {"id": "wi-b", "days": {"p10": 1, "p50": 60, "p80": 70, "p90": 80}, "ddr": [], "action": ["ddr-y"],
                 "dates": {"p10": "2026-11-19", "p50": "2027-01-17", "p80": "2027-01-27", "p90": "2027-02-06"}}],
      "gates": {"undated": [{"id": "wi-e", "why": "after another project: acme wi-z", "milestone": "ms-demo-loose"},
                            {"id": "wi-ext", "why": "blocked", "milestone": ""}]}}


@pytest.fixture
def st(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(NODES)
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(EDGES)
    return resume.Store.load(store)


def _find(nodes, key):
    for n in nodes:
        if n["key"] == key:
            return n
        hit = _find(n["children"], key)
        if hit:
            return hit
    return None


def _ids(node):
    return [c["id"] or c["name"] for c in node["children"]]


def test_the_thematic_axis_is_era_milestone_item_with_counts_bars_and_the_forecast(st):
    roots = planviews.tree(st, FC, "milestones", "demo")
    assert [r["key"] for r in roots] == ["demo:era-demo-one", "demo:(no era)", "demo:(no milestone)"]
    era = roots[0]
    assert _ids(era) == ["ms-demo-core"]   # the waves are the other axis
    core = _find(roots, "demo:ms-demo-core")
    # counted through its sub-milestone (wi-b), the dropped item left out: a, b, c, carry; c done
    assert (core["done"], core["items"]) == (1, 4) and core["when"] == "Nov 20 – Dec 4"
    assert core["gates"] == ["calendar 2026-12-01"]
    # its sub-milestone first, then the open items (doing first, then by priority), the done ones folded last
    assert _ids(core) == ["ms-demo-sub", "wi-a", "wi-carry", "1 done"]
    done = core["children"][-1]
    assert done["kind"] == "done" and done["fold"] and [c["id"] for c in done["children"]] == ["wi-c"]
    a = _find(roots, "demo:wi-a")
    assert (a["state"], a["priority"], a["gates"], a["when"]) == ("doing", "P2", ["ddr"], "Nov 19 – Nov 22")
    b = _find(roots, "demo:wi-b")
    assert b["gates"] == ["action"] and b["when"] == "Nov 19 – beyond 6 weeks"
    loose = roots[1]["children"]
    assert [m["id"] for m in loose] == ["ms-demo-loose", "ms-x"] and loose[0]["when"] == "undated: 1 item(s) not dated"
    e = _find(roots, "demo:wi-e")
    assert e["priority"] == "P3?" and e["gates"] == ["outside"] and e["when"] == "undated: after another project"
    # no thematic milestone: the wave's alone and the dropped milestone's; folded
    stray = roots[2]
    assert stray["fold"] and sorted(c["id"] for c in stray["children"]) == ["wi-ext", "wi-one", "wi-two", "wi-w"]
    assert "ms-demo-gone" not in json.dumps(roots)


def test_the_wave_axis_puts_a_carried_item_in_the_wave_it_is_in_now(st):
    roots = planviews.tree(st, FC, "waves", "demo")
    era = roots[0]
    assert _ids(era) == ["wave-s1", "wave-s2"]   # in their release's order
    s1, s2 = era["children"]
    assert s1["name"] == "0.1.0 (wave-s1)" and s1["when"] == "reached Nov 10" and (s1["done"], s1["items"]) == (1, 1)
    assert sorted(c["id"] for c in s2["children"]) == ["wi-a", "wi-carry", "wi-w"] and s2["items"] == 3
    assert roots[-1]["key"] == "demo:(no wave)" and sorted(c["id"] for c in roots[-1]["children"]) == [
        "wi-b", "wi-e", "wi-ext", "wi-one", "wi-two"]
    with pytest.raises(ValueError):
        planviews.tree(st, FC, "priority", "demo")


def test_without_a_forecast_the_tree_says_how_to_get_one(st):
    roots = planviews.tree(st, None, "milestones", "demo")
    assert _find(roots, "demo:ms-demo-core")["when"] == "" and _find(roots, "demo:wi-a")["when"] == ""
    assert planviews.heading(None) == "no forecast yet: brain forecast"
    assert planviews.heading(FC) == "ranges p10–p90 UNCALIBRATED (1 of 5 judged), forecast of 2026-11-18 08:00 UTC"


def test_the_labels_drop_the_bar_under_120_columns_and_the_legacy_console_gets_words(st, monkeypatch):
    core = _find(planviews.tree(st, FC, "milestones", "demo"), "demo:ms-demo-core")
    wide, narrow = planviews.label(core, 1, 120, plain=False), planviews.label(core, 1, 100, plain=False)
    assert "██" in wide and "█" not in narrow and "Nov 20 – Dec 4" in narrow and "⧗ calendar" in wide
    a = _find(planviews.tree(st, FC, "milestones", "demo"), "demo:wi-a")
    assert planviews.label(a, 2, plain=False).startswith("● P2  wi-a") and "⧗ DDR" in planviews.label(a, 2, plain=False)
    monkeypatch.setenv("TERM", "linux")
    assert planviews.words() and planviews.label(a, 2).startswith("doing P2  wi-a") and "●" not in planviews.label(a, 2)
    panel = {"projects": [planviews.collect(st, FC, "demo")]}
    text = "\n".join(planviews.lines(panel, "milestones", 120))
    assert "|-- " in text and "├" not in text and "█" not in text


def test_the_text_twin_draws_the_tree_and_folds_the_groups(st):
    panel = {"projects": [planviews.collect(st, FC, "demo")]}
    out = planviews.lines(panel, "milestones", 120, plain=False)
    assert out[0] == "Milestones · Tree · axis: milestones" and out[1].startswith("  ranges p10–p90 UNCALIBRATED")
    text = "\n".join(out)
    assert "├── ▾ era-demo-one" in text and "▸ ✓ 1 done" in text and not re.search(r"wi-c\b", text)   # folded
    assert "└── ▸ (no milestone)  4 open item(s)" in text and "wi-ext" not in text
    assert all(len(x) <= 120 for x in out)
    waves = "\n".join(planviews.lines(panel, "waves", 120, plain=False))
    assert "✓ 0.1.0 (wave-s1)" in waves and "0.2.0 (wave-s2)" in waves and "(no wave)  5 open item(s)" in waves


def test_brain_tui_once_prints_the_tree_and_refuses_a_bad_view(st, store, capsys):
    root = store.parents[1]
    forecast.folder(root.name).mkdir(parents=True, exist_ok=True)
    (forecast.folder(root.name) / "latest.json").write_text(json.dumps(FC), encoding="utf-8")
    assert cli.main(["--root", str(root), "tui", "--once", "--quick", "--tab", "milestones", "--view", "tree",
                     "--axis", "waves"]) == 0
    out = capsys.readouterr().out
    assert "Milestones · Tree · axis: waves" in out and "0.2.0 (wave-s2)" in out and "Milestones (" not in out
    assert cli.main(["--root", str(root), "tui", "--once", "--quick", "--tab", "milestones"]) == 0
    out = capsys.readouterr().out   # without --view: the tab's list, the tree only when asked
    assert "Milestones (" in out and "· Tree ·" not in out
    for bad in (["--view", "tree"], ["--tab", "queue", "--view", "tree"], ["--tab", "milestones", "--view", "nope"]):
        with pytest.raises(SystemExit):
            cli.main(["--root", str(root), "tui", "--once", "--quick", *bad])


def test_the_cockpit_reads_the_plan_again_when_the_forecast_changes(st, store):
    root = store.parents[1]
    p = projects.Project(name="demo", root=root, stores=[store])
    cp = cockpit.Cockpit([p], root=root)
    cp.refresh()
    plan = cp.snapshot()["panels"]["plan"]
    assert plan["projects"][0]["forecast"] == "no forecast yet: brain forecast"
    assert cockpit.heading("plan", plan) == "Milestones · Tree · no forecast yet: brain forecast"
    forecast.folder("demo").mkdir(parents=True, exist_ok=True)
    (forecast.folder("demo") / "latest.json").write_text(json.dumps(FC), encoding="utf-8")
    assert "plan" in cp.refresh() and cp.snapshot()["panels"]["plan"]["projects"][0]["as_of"] == FC["as_of"]
    assert "plan" not in cp.refresh()   # nothing changed


def test_the_axis_is_data_and_kept_with_the_tabs_view():
    assert cockpit.MODES["plan"]["axes"] == planviews.AXES and cockpit.tab_axes("milestones") == planviews.AXES
    assert cockpit.tab_axes("queue") == () and cockpit.axis_of("plan", "waves") == "waves"
    assert cockpit.axis_of("plan", "people") == "milestones"   # a newer brain's axis: the default
    assert cockpit.TABS["milestones"]["views"]["tree"] == ("plan",) and cockpit.panel_tab("plan") == "milestones"
    kept = cockpit._saved_tabs({"tabs": {"milestones": {"view": "tree", "axis": "waves"},
                                         "queue": {"view": "list", "axis": "waves"}}})
    assert kept["tabs"] == {"milestones": {"view": "tree", "axis": "waves"}, "queue": {"view": "list"}}
    assert cockpit._saved_tabs({"tabs": {"milestones": {"view": "tree", "axis": "people"}}})["tabs"] == {
        "milestones": {"view": "tree"}}
