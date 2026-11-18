"""wi-brain-tui-waves: the Milestones Tree's waves axis in the Textual app (brain.tui_plan): a wave's lots, f the P0
and P1 items alone, the session on each item redrawn when the sessions change (the data is brain.planviews', tested
in test_planwaves)."""

from test_planviews import FC
from test_planwaves import EDGES, MORE_EDGES, MORE_NODES, NODES, SESSIONS
from test_tui import PANELS, FakeCockpit  # skipped with it, without Textual: first
from test_tui_plan import _all, _labels, _run

from brain import planviews, resume
from brain.tui_plan import PlanTree


class WavesCockpit(FakeCockpit):
    def __init__(self, plan):
        super().__init__()
        self.plan, self.sessions = plan, {"hours": 24, "rows": []}

    def refresh(self, probe=False):
        self.calls.append(probe)
        return set()

    def snapshot(self):
        return {"scope": self.scope, "read_at": "2026-11-18T10:00:00Z", "probed_at": None,
                "panels": {**PANELS, "sessions": self.sessions, "plan": self.plan}}


def _plan(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(NODES + MORE_NODES)
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(EDGES + MORE_EDGES)
    return {"projects": [planviews.collect(resume.Store.load(store), FC, "demo")]}


def test_the_waves_axis_shows_the_lots_filters_p0_p1_and_follows_the_sessions(store):
    fake = WavesCockpit(_plan(store))

    async def check(app, pilot, fake):
        tree = app.query_one("#plan", PlanTree)
        s2 = next(n for n in _all(tree) if (n.data or {}).get("id") == "wave-s2")
        s2.expand()
        await pilot.pause(0.1)
        labels = _labels(tree)
        assert any(x.startswith("round 1 · lot 2 (2)  wi-x2 P0 → wi-x1 P1") for x in labels)
        assert any(x.startswith("● P2  wi-a") for x in labels)   # the lots open: a wave unfolded shows its items
        assert "f P0/P1 only" in str(tree.border_subtitle)
        tree.focus()
        await pilot.press("f")
        await pilot.pause(0.1)
        labels = _labels(tree)
        assert app.plan_urgent and "P0/P1 only · f all" in str(tree.border_subtitle)
        assert any(x.startswith("○ P0  wi-x2") for x in labels) and not any("wi-a" in x for x in labels)
        await pilot.press("f")   # every item again, the lot hidden meanwhile still open
        await pilot.pause(0.1)
        assert not app.plan_urgent and any(x.startswith("● P2  wi-a") for x in _labels(tree))
        fake.sessions = SESSIONS   # a session now works on wi-a: the tree redrawn
        app.draw({"sessions"})
        await pilot.pause(0.1)
        assert any(x.startswith("● P2  wi-a") and "session s8-x" in x for x in _labels(tree))
        drawn = app.plan_working
        app.draw({"sessions"})   # the same sessions: not redrawn
        assert app.plan_working is drawn
    _run(check, fake, tab="milestones", tabs={"milestones": {"view": "tree", "axis": "waves"}})
