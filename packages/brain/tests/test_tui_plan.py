"""wi-brain-tui-plan-tree: the Milestones tab's Tree in the Textual app (brain.tui_plan): v to the Tree, g the axis,
←/→ fold, Enter the detail, the axis saved with the tab's view (the data is brain.planviews', tested in
test_planviews)."""

import asyncio

from test_planviews import EDGES, FC, NODES  # the fixture graph and forecast
from test_tui import PANELS, FakeCockpit, _hold_the_timer  # skipped with it, without Textual

from brain import cockpit, planviews, resume, tui
from brain.tui_plan import PlanTree, opened


def _run(test, fake, size=(160, 48), **kw):
    async def main():
        app = tui.CockpitApp(fake, refresh=2.0, probe=300, **kw)
        async with app.run_test(size=size) as pilot:
            await pilot.pause(0.2)
            await app.workers.wait_for_complete()
            _hold_the_timer(app)
            await pilot.pause(0.1)
            await test(app, pilot, fake)
    asyncio.run(main())


class PlanCockpit(FakeCockpit):
    def __init__(self, plan):
        super().__init__()
        self.plan = plan

    def refresh(self, probe=False):
        self.calls.append(probe)
        return {*cockpit.PANELS, "plan"}

    def snapshot(self):
        return {"scope": self.scope, "read_at": "2026-11-18T10:00:00Z", "probed_at": None,
                "panels": {**PANELS, "plan": self.plan}}


def _plan(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(NODES)
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(EDGES)
    return {"projects": [planviews.collect(resume.Store.load(store), FC, "demo")]}


def _labels(tree):
    out, stack = [], list(reversed(tree.root.children))
    while stack:
        n = stack.pop()
        out.append(str(n.label))
        if n.is_expanded:
            stack.extend(reversed(n.children))
    return out


def test_the_tree_view_its_axis_its_folds_and_its_detail(store, monkeypatch):
    plan = _plan(store)
    opened_details, saved = [], []
    monkeypatch.setattr(cockpit, "save_state", lambda state, path=None: saved.append(state) or True)

    async def check(app, pilot, fake):
        await pilot.press("4")
        assert app.tab == "milestones" and app._view() == "list"
        await pilot.press("v")
        await pilot.pause(0.1)
        tree = app.query_one("#plan", PlanTree)
        assert app._view() == "tree" and app.focused is tree and tree.display
        labels = _labels(tree)
        assert labels[0].startswith("era-demo-one") and any(x.startswith("core") for x in labels)
        assert "axis: milestones" in str(tree.border_subtitle)
        assert not any("wi-a " in x for x in labels)   # a milestone's items show once it is unfolded
        await pilot.press("g")
        await pilot.pause(0.1)
        assert app.plan_axis == "waves" and "axis: waves" in str(tree.border_subtitle)
        assert any("0.2.0 (wave-s2)" in x for x in _labels(tree))
        assert saved[-1]["tabs"]["milestones"] == {"view": "tree", "axis": "waves"}
        await _folds_and_detail(app, pilot, tree, opened_details)
    _run(check, PlanCockpit(plan), tabs={"milestones": {"view": "list"}})


async def _folds_and_detail(app, pilot, tree, opened_details):
    """→ unfolds then goes to the first child, ← to the parent then folds, Enter a detail, space the pause, a refresh
    keeps the cursor."""
    s2 = next(n for n in _all(tree) if (n.data or {}).get("id") == "wave-s2")
    tree.move_cursor(s2)
    await pilot.press("right")   # unfolds it
    assert s2.is_expanded and any("wi-carry" in x for x in _labels(tree))
    await pilot.press("right")   # then goes to its first child: a lot (wi-brain-tui-waves), open
    lot = s2.children[0]
    assert tree.cursor_node is lot and lot.data["kind"] == "lot" and lot.is_expanded
    await pilot.press("right")   # its first item
    assert tree.cursor_node is lot.children[0]
    app.open_detail = lambda name, r: opened_details.append((name, r["id"]))
    await pilot.press("enter")
    assert opened_details == [("frontier", lot.children[0].data["id"])]
    await pilot.press("left")    # an item: to its parent
    assert tree.cursor_node is lot
    await pilot.press("left", "left")    # the lot folds, then to the wave
    assert not lot.is_expanded and tree.cursor_node is s2
    await pilot.press("left")    # folds it
    assert not s2.is_expanded
    await pilot.press("enter")   # a wave: its detail
    assert opened_details[-1] == ("milestones", "wave-s2")
    paused = app.paused
    await pilot.press("space")   # the cockpit's pause, not the tree's toggle
    assert app.paused is not paused and not s2.is_expanded
    app.draw({"plan"})   # a refresh keeps the cursor's key
    await pilot.pause(0.1)
    assert (tree.cursor_node.data or {}).get("id") == "wave-s2"


def _all(tree):
    out, stack = [], list(tree.root.children)
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(n.children)
    return out


def test_started_on_the_tree_before_a_read_keeps_the_first_open_nodes(store):
    """The app started on the Tree draws it empty first: the default open nodes still apply once the plan is read."""
    plan = _plan(store)
    fake = PlanCockpit(None)

    async def check(app, pilot, fake):
        tree = app.query_one("#plan", PlanTree)
        assert app._view() == "tree" and app.plan_open is None
        fake.plan = plan
        app.draw({"plan"})
        await pilot.pause(0.1)
        assert any(x.startswith("core") for x in _labels(tree))   # the era open, as at first
    _run(check, fake, tab="milestones", tabs={"milestones": {"view": "tree"}})


def test_the_first_open_nodes_are_the_roots_and_their_groups(store):
    plan = _plan(store)
    nodes = plan["projects"][0]["trees"]["milestones"]
    keys = opened(nodes)
    assert "demo:era-demo-one" in keys and "demo:(no era)" in keys
    assert "demo:(no milestone)" not in keys and "demo:ms-demo-core" not in keys   # folded, a milestone closed
    assert tui.PlanTree is PlanTree and "plan" in tui.EVERY_FRAME
