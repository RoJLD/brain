"""wi-brain-tui-trajectories-bands and -items: the Milestones tab's Trajectories in the Textual app (brain.tui_plan
TrajView): Enter on a Tree milestone opens its row there, [ ] the scale, ←/→ the pan, z or Enter a row's items, c the
critical chain, Enter an item's or the milestone's detail, Z or Escape back, a refresh keeps the level and the row (the
data and the text are brain.planbands', tested in test_planbands and test_planitems)."""

from test_planbands import FCB
from test_planviews import EDGES, NODES
from test_tui_plan import PlanCockpit, _all, _run  # skipped with test_tui, without Textual: first

from brain import planbands, planviews, resume, tui
from brain.tui_plan import PlanTree, TrajView, band_keys, traj_options


def _plan(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(NODES)
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(EDGES)
    st = resume.Store.load(store)
    return {"projects": [{**planviews.collect(st, FCB, "demo"), "bands": planbands.collect(st, FCB, "demo")}]}


def _row_id(view):
    return view.get_option_at_index(view.highlighted).id


def test_enter_on_a_tree_milestone_opens_its_trajectory_and_the_keys_scale_and_pan(store):
    plan = _plan(store)
    opened = []

    async def check(app, pilot, fake):
        app.open_detail = lambda name, r: opened.append((name, r["id"]))
        tree = app.query_one("#plan", PlanTree)
        core = next(n for n in _all(tree) if (n.data or {}).get("id") == "ms-demo-core")
        tree.move_cursor(core)
        await pilot.press("enter")
        await pilot.pause(0.2)
        view = app.query_one("#traj", TrajView)
        assert app._view() == "trajectories" and app.focused is view and opened == []
        assert _row_id(view) == "demo:ms-demo-core" and "▒ p10–p80" in str(view.border_subtitle)
        assert "Trajectories" in str(view.border_title)
        width = view._width()
        start = planbands.default_scale(planbands.cells(width))
        await pilot.press("right_square_bracket")
        assert view.scale == planbands.zoom(start, 1)
        await pilot.press("left_square_bracket", "left_square_bracket")
        assert view.scale == planbands.zoom(start, -1)
        await pilot.press("right")
        assert view.pan_at == planbands.pan(0, view.scale, 1)
        await pilot.press("left")
        assert view.pan_at == 0
        await pilot.press("enter")   # a milestone's row: its items (wi-brain-tui-trajectories-items)
        assert view.level == "demo:ms-demo-core" and opened == []
        await pilot.press("enter")   # the item level's heading: the milestone's detail
        assert opened == [("milestones", "ms-demo-core")]
        await pilot.press("Z")
        assert view.level is None and _row_id(view) == "demo:ms-demo-core"
        app.draw({"plan"})   # a refresh keeps the row, the scale and the pan
        await pilot.pause(0.1)
        assert _row_id(view) == "demo:ms-demo-core" and view.scale == planbands.zoom(start, -1)
        view.highlighted = next(i for i in range(view.option_count)
                                if view.get_option_at_index(i).id == "demo:(backlog)")
        await pilot.press("enter")   # the backlog's row: no detail, no items
        assert opened == [("milestones", "ms-demo-core")] and view.level is None
    _run(check, PlanCockpit(plan), tab="milestones", tabs={"milestones": {"view": "tree"}})


def _plan_items(store):
    from test_planitems import FCI
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(NODES)
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(EDGES)
    st = resume.Store.load(store)
    tree = planviews.collect(st, FCI, "demo")
    return {"projects": [{**tree, "bands": planbands.collect(st, FCI, "demo", tree["trees"])}]}


def test_z_shows_a_milestones_items_c_marks_the_chain_and_escape_goes_back(store):
    plan = _plan_items(store)
    opened = []

    async def check(app, pilot, fake):
        app.open_detail = lambda name, r: opened.append((name, r["id"]))
        app.action_set_view("trajectories")
        await pilot.pause(0.2)
        view = app.query_one("#traj", TrajView)
        view.focus()
        view.highlighted = next(i for i in range(view.option_count)
                                if view.get_option_at_index(i).id == "demo:ms-demo-core")
        await pilot.press("z")
        assert view.level == "demo:ms-demo-core" and "critical chain: c" in str(view.border_subtitle)
        prompts = [str(view.get_option_at_index(i).prompt) for i in range(view.option_count)]
        assert prompts[0].startswith("demo › core › items · in the scheduler's order")
        assert not any(p.startswith("critical (most futures)") for p in prompts) and "◆" not in "".join(prompts)
        await pilot.press("c")   # the chain marked, its line in the heading
        prompts = [str(view.get_option_at_index(i).prompt) for i in range(view.option_count)]
        assert prompts[1].startswith("critical (most futures): wi-a 70% → wi-b 100%")
        b = next(i for i in range(view.option_count) if view.get_option_at_index(i).id == "demo:wi-b")
        assert str(view.get_option_at_index(b).prompt).endswith("◆")
        view.highlighted = b
        await pilot.press("enter")   # an item: its detail
        assert opened == [("frontier", "wi-b")]
        app.draw({"plan"})   # a refresh keeps the level, the mark and the row
        await pilot.pause(0.1)
        assert view.level == "demo:ms-demo-core" and view.chain_on and _row_id(view) == "demo:wi-b"
        await pilot.press("escape")   # out of the items, the cursor on the milestone's row
        assert view.level is None and _row_id(view) == "demo:ms-demo-core" and app.tab == "milestones"
        await pilot.press("escape")   # then the cockpit's own back
        assert app.tab == "overview"
    _run(check, PlanCockpit(plan), tab="milestones", tabs={"milestones": {"view": "trajectories"}})


def test_a_tree_milestone_the_forecast_has_no_row_for_opens_its_detail(store):
    plan = _plan(store)
    opened = []

    async def check(app, pilot, fake):
        app.open_detail = lambda name, r: opened.append((name, r["id"]))
        tree = app.query_one("#plan", PlanTree)
        x = next(n for n in _all(tree) if (n.data or {}).get("id") == "ms-x")
        tree.move_cursor(x)
        await pilot.press("enter")
        assert opened == [("milestones", "ms-x")] and app._view() == "tree"
    _run(check, PlanCockpit(plan), tab="milestones", tabs={"milestones": {"view": "tree"}})


def test_the_options_and_the_keys_of_the_rows(store):
    plan = _plan(store)
    assert "demo:ms-demo-core" in band_keys(plan) and "demo:(backlog)" not in band_keys(plan)
    options, rows = traj_options(plan, 120, None, 0)
    assert options[0].disabled and "Nov 23" in str(options[0].prompt)   # the dates' row, one project: no heading
    assert [o.id for o in options[1:3]] == ["demo:wave-s2", "demo:ms-demo-core"] and rows["demo:wave-s2"]["kind"] == (
        "wave")
    two = {"projects": [*plan["projects"], {"project": "acme", "error": "OSError: gone"}]}
    options, _ = traj_options(two, 120, None, 0)
    assert str(options[0].prompt).startswith("demo: ranges p10–p90") and str(options[-1].prompt) == (
        "acme: error: OSError: gone")
    assert [str(o.prompt) for o in traj_options(None, 120, None, 0)[0]] == ["not read yet"]
    assert "traj" in tui.EVERY_FRAME and tui.TrajView is TrajView
