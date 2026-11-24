"""wi-brain-milestone-order: the Milestones tab's Path view in the Textual app (brain.tui_path PathView): the lanes from
120 screen columns, ←/→ the milestone of the row, Enter its detail (a knot's: its pairs and how to settle it), the tree
under 120 columns, a refresh keeps the row and the rank (the data and the text are brain.planpath's, tested in
test_planpath)."""

from test_planpath import EDGES, FC, NODES
from test_tui_plan import PlanCockpit, _run  # skipped with test_tui, without Textual: first

from brain import planpath, planviews, resume, tui
from brain.tui_path import PathView, lane_text, path_options, picked_col
from brain.tui_screens import ResultScreen


def _plan(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(NODES)
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(EDGES)
    st = resume.Store.load(store)
    return {"projects": [{**planviews.collect(st, FC, "demo"), "path": planpath.layers(st, FC, "demo")}]}


def _row(view):
    return view.rows[view.get_option_at_index(view.highlighted).id]


def test_the_lanes_pick_a_milestone_and_enter_opens_its_detail_or_the_knot(store):
    plan = _plan(store)
    opened = []

    async def check(app, pilot, fake):
        app.open_detail = lambda name, r: opened.append((name, r["id"], r["done"], r["items"]))
        view = app.query_one("#path", PathView)
        assert app._view() == "path" and "Path" in str(view.border_title) and "←/→ milestone" in str(
            view.border_subtitle)
        view.focus()
        await pilot.pause(0.1)
        r = _row(view)
        assert r["mode"] == "lanes" and [c[0] for c in r["cells"]] == ["ms-demo-a", "ms-demo-b", "ms-demo-c"]
        assert view.picked() == ("demo", "ms-demo-a")
        await pilot.press("right", "right")
        assert view.col == 2 and view.picked() == ("demo", "ms-demo-c")
        await pilot.press("right")   # the row's last: it stays
        assert view.col == 2
        await pilot.press("enter")
        assert opened == [("milestones", "ms-demo-c", 0, 2)]
        app.draw({"plan"})   # a refresh keeps the row and the rank
        await pilot.pause(0.1)
        assert view.col == 2 and view.picked() == ("demo", "ms-demo-c")
        await pilot.press("left", "left", "down")   # the second row: the knot, then g
        assert _row(view)["cells"][0][0] == "knot:ms-demo-d+ms-demo-e"
        assert view.picked() == ("demo", "knot:ms-demo-d+ms-demo-e")   # its rank 2 is empty: the first filled
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert isinstance(app.screen, ResultScreen) and "a mutual wait" in app.screen.title_text
        assert "wi-d1 waits on wi-e1" in app.screen.results[0]["output"]
    _run(check, PlanCockpit(plan), tab="milestones", tabs={"milestones": {"view": "path"}})


def test_under_120_columns_the_path_is_a_tree(store):
    plan = _plan(store)
    opened = []

    async def check(app, pilot, fake):
        app.open_detail = lambda name, r: opened.append(r["id"])
        view = app.query_one("#path", PathView)
        view.focus()
        await pilot.pause(0.1)
        assert _row(view) == {"mode": "tree", "project": "demo", "node": "ms-demo-a"}
        await pilot.press("down", "enter")
        assert opened == ["ms-demo-b"]
    _run(check, PlanCockpit(plan), size=(110, 40), tab="milestones", tabs={"milestones": {"view": "path"}})


def test_the_options_and_a_lanes_row_marked(store):
    plan = _plan(store)
    options, rows, lays = path_options(plan, 140, 140)
    assert options[0].disabled and str(options[0].prompt).startswith("rank 1")   # one project: no heading
    assert options[1].id == "demo:0" and rows["demo:0"]["mode"] == "lanes" and lays["demo"]["v"] == 1
    marked = lane_text(rows["demo:0"], 1)
    assert any(s.style == "reverse" for s in marked.spans) and "a 1/2" in marked.plain
    assert not any(s.style == "reverse" for s in lane_text(rows["demo:0"], None).spans)
    second = rows["demo:1"]   # the knot, g, and an empty third rank: the picked rank 3 falls back to the first
    assert picked_col(second, 2) == 0 and picked_col(second, 1) == 1
    shown = next(s for s in lane_text(second, picked_col(second, 2)).spans if s.style == "reverse")
    assert shown.start == 0   # the cell shown reversed is the one Enter opens
    two = {"projects": [*plan["projects"], {"project": "acme", "error": "OSError: gone"}]}
    options, _, _ = path_options(two, 140, 140)
    assert str(options[0].prompt).startswith("demo: 10 milestone(s)") and str(options[-1].prompt) == (
        "acme: error: OSError: gone")
    assert [str(o.prompt) for o in path_options(None, 140, 140)[0]] == ["not read yet"]
    assert "path" in tui.EVERY_FRAME and tui.PathView is PathView
