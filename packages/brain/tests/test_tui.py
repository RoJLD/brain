"""wi-brain-tui-cockpit and wi-brain-tui-view-controls: the Textual app, thinly (its data, rows, filters and sorts
are brain.cockpit's, tested in test_cockpit)."""

import asyncio

import pytest

pytest.importorskip("textual")

from textual.markup import escape  # noqa: E402
from textual.widgets import DataTable, Select  # noqa: E402

from brain import cockpit, tui  # noqa: E402


def _session(sid, state, project="demo", age_s=30):
    return {"state": state, "session_id": sid, "project": project, "step": "2/3 Write", "model": "claude-opus-5-5",
            "effort": "high", "context": 250_000, "budget": 600_000, "output_tokens": 4500, "age_s": age_s,
            "title": f"Task {sid}", "branch": "b"}


def _item(iid, priority, unblocks, title, project="demo"):
    return {"id": iid, "priority": priority, "milestone": "ms-demo-x", "unblocks": unblocks, "age_days": 1,
            "since": "", "title": title}


PANELS = {
    "sessions": {"hours": 24, "rows": [_session("abcdef123456", "asking"), _session("ended0000000", "ended")]},
    "queue": {"projects": [{"project": "demo", "counts": {"decision": 2}, "entries": [
        {"id": "ddr-a", "kind": "decision", "unblocks": 1, "age_days": 0, "title": "Pick a layout", "since": ""},
        {"id": "ddr-b", "kind": "decision", "unblocks": 4, "age_days": 2, "title": "Pick a theme", "since": ""}]}]},
    "milestones": {"projects": [{"project": "demo", "reached": 1,
                                 "pending": [{"id": "ms-x", "title": "X", "items": 4, "done": 1}]}]},
    "frontier": {"projects": [{"project": "demo", "items": [_item("wi-one", "P0", 0, "First"),
                                                            _item("wi-two", "P2", 5, "Second, the TUI"),
                                                            _item("wi-three", "P1", 1, "Third")]}]},
    "audit": {"projects": [{"project": "demo", "counts": {"P0": 1}, "repos": 1, "unreadable": [], "top": []}]},
}


class FakeCockpit:
    def __init__(self):
        self.calls, self.selected = [], []
        self.scope, self.every = "demo", False
        self.choices = {"demo": None, "quant": None}

    @property
    def multi(self):
        return self.every

    def select(self, scope):
        self.selected.append(scope)
        self.scope, self.every = scope, scope == cockpit.ALL

    def needs_probe(self):
        return False

    def refresh(self, probe=False):
        self.calls.append(probe)
        return set(cockpit.PANELS)

    def snapshot(self):
        return {"scope": self.scope, "read_at": "2026-11-02T10:00:00Z", "probed_at": None, "panels": PANELS}


def _run(test, **kw):
    async def main():
        fake = FakeCockpit()
        app = tui.CockpitApp(fake, refresh=2.0, probe=300, **kw)
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause(0.2)
            await app.workers.wait_for_complete()
            await pilot.pause(0.1)
            await test(app, pilot, fake)
    asyncio.run(main())


def _ids(app, name):
    table = app.query_one(f"#{name}", DataTable)
    return [table.get_row_at(i)[table.ordered_columns.index(next(c for c in table.ordered_columns
                                                                 if str(c.label) == "Id"))]
            for i in range(table.row_count)]


def test_the_app_draws_the_panels_and_answers_its_keys():
    async def check(app, pilot, fake):
        assert fake.calls == [False]  # the files first, the probes at the next tick
        sessions = app.query_one("#sessions")
        assert sessions.row_count == 1  # the ended session hidden by default
        assert sessions.border_title.startswith("1 Sessions (2 in the last 24 h, 1 asking")
        assert sessions.border_subtitle == "1 of 2 shown; state open; sort state"
        assert app.query_one("#queue").row_count == 2 and app.query_one("#milestones").row_count == 1
        assert app.query_one("#audit").border_title == escape("6 Audit debt [i]")
        assert "demo | files every 2 s, checked " in app.sub_title and app.sub_title.endswith("| local")
        assert [str(c.label) for c in sessions.ordered_columns][:6] == ["State", "Session", "Role", "Parent", "Kids",
                                                                     "Step"]  # one project: no Project column
        await pilot.press("r")
        await app.workers.wait_for_complete()
        assert fake.calls[-1] is True
        await pilot.press("minus")
        assert app.refresh_s == 5.0
        await pilot.press("plus", "plus", "plus", "plus")
        assert app.refresh_s == 0.5  # the shortest
        app.query_one("#sessions").focus()
        await pilot.press("m")
        assert app.screen.maximized is app.query_one("#sessions")
        assert sessions.border_title.startswith(escape("demo > 1 Sessions"))  # the full view's breadcrumb
        await pilot.press("5")  # another panel while one is maximized: that one, maximized
        assert app.screen.maximized is app.query_one("#frontier") and app.focused is app.query_one("#frontier")
        assert app.query_one("#frontier").border_title.startswith(escape("demo > 5 Frontier"))
        assert not sessions.border_title.startswith("demo")
        await pilot.press("escape")  # back to the main view
        assert app.screen.maximized is None and app.query_one("#frontier").border_title.startswith("5 Frontier")
        await pilot.press("question_mark")
        assert app.screen.query("HelpPanel")
        await pilot.press("question_mark")
        await pilot.pause(0.1)
        assert not app.screen.query("HelpPanel")
    _run(check)


def test_sort_filter_and_search_change_the_tables_and_are_remembered():
    async def check(app, pilot, fake):
        await pilot.press("5")
        assert _ids(app, "frontier") == ["wi-one", "wi-three", "wi-two"]  # by priority
        table = app.query_one("#frontier", DataTable)
        table.move_cursor(row=2)  # on wi-two
        await pilot.press("s")  # the next sort: unblocks
        assert _ids(app, "frontier") == ["wi-two", "wi-three", "wi-one"]
        assert table.cursor_row == 0  # the cursor follows its record
        assert table.border_subtitle == "sort unblocks"
        await pilot.press("o")
        assert _ids(app, "frontier") == ["wi-one", "wi-three", "wi-two"] and app.views["frontier"]["reverse"]
        state = cockpit.load_state()
        assert state["scope"] == "demo" and state["panels"]["frontier"]["sort"] == "unblocks"
        assert state["panels"]["frontier"]["reverse"] is True
        await pilot.press("f")  # the filter dialog
        await pilot.pause(0.1)
        dialog = app.screen
        assert isinstance(dialog, tui.ViewScreen)
        dialog.query_one("#f-priority", Select).value = "P0-P1"
        await pilot.click("#apply")
        await pilot.pause(0.1)
        assert app.screen is not dialog and _ids(app, "frontier") == ["wi-one", "wi-three"]  # unblocks, reversed
        assert app.views["frontier"]["priority"] == "P0-P1"
        await pilot.press("f")
        await pilot.pause(0.1)
        await pilot.click("#reset")
        await pilot.pause(0.1)
        assert app.views["frontier"] == cockpit.view_of("frontier")
        await pilot.press("f", "escape")  # cancelled: nothing changes
        assert app.views["frontier"] == cockpit.view_of("frontier")
        await pilot.press("slash")
        assert app.focused is app.query_one("#search")
        await pilot.press(*"tui")
        assert _ids(app, "frontier") == ["wi-two"] and app.query_one("#queue").row_count == 0
        assert "q" not in [b for b in "tui"] and app.is_running  # the letters went to the search, not the keys
        await pilot.press("escape")  # cleared, back to the panel
        assert app.search == "" and app.focused is app.query_one("#frontier") and len(_ids(app, "frontier")) == 3
        await pilot.press("2")
        await pilot.press("s", "s", "s")  # the queue: band, unblocks, age, kind
        assert app.views["queue"]["sort"] == "kind"
        await pilot.press("8", "s")  # a panel without a view: s does nothing
        assert app.is_running
    _run(check)


def test_a_column_title_sorts_and_the_project_selector_changes_the_scope():
    async def check(app, pilot, fake):
        table = app.query_one("#queue", DataTable)
        band = next(c for c in table.ordered_columns if str(c.label) == "Band")
        table.post_message(DataTable.HeaderSelected(table, band.key, 0, band.label))
        await pilot.pause(0.1)
        assert app.views["queue"] == {**cockpit.view_of("queue"), "reverse": True}  # its sort already: reversed
        age = next(c for c in table.ordered_columns if str(c.label) == "Age")
        table.post_message(DataTable.HeaderSelected(table, age.key, 5, age.label))
        await pilot.pause(0.1)
        assert app.views["queue"]["sort"] == "age" and not app.views["queue"]["reverse"]
        await pilot.press("p")
        select = app.query_one("#scope", Select)
        assert select.expanded and select in app.focused.ancestors_with_self  # its list opened
        select.value = cockpit.ALL
        await pilot.pause(0.2)
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)
        assert fake.selected == ["all"] and app.scope == "all" and cockpit.load_state()["scope"] == "all"
        assert "Project" in [str(c.label) for c in app.query_one("#sessions").ordered_columns]  # several projects
        assert app.sub_title.startswith("all |")
    _run(check)


def test_the_app_starts_from_the_views_it_is_given():
    async def check(app, pilot, fake):
        assert _ids(app, "frontier") == ["wi-two", "wi-three", "wi-one"] and app.query_one("#sessions").row_count == 2
        await pilot.press("slash", *"task end")  # every table: the sessions' titles too
        assert app.query_one("#sessions").row_count == 1 and app.query_one("#frontier").row_count == 0
        assert app.query_one("#sessions").border_subtitle == "1 of 2 shown; state all; search 'task end'; sort state"
    _run(check, views={"sessions": {"state": "all"}, "frontier": {"sort": "unblocks"}})


def test_an_error_in_a_read_is_shown_not_fatal():
    async def check(app, pilot, fake):
        def boom(probe=False):
            raise OSError("disk gone")
        fake.refresh = boom
        app.busy = False
        app.tick(probe=False)
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert not app.busy and app.is_running
    _run(check)


def _many(n, age0=0):
    return {**PANELS, "sessions": {"hours": 24, "rows": [_session(f"s{i:02d}xxxxxxx", "running", age_s=age0 + i)
                                                         for i in range(n)]}}


def test_a_refresh_keeps_the_scroll_and_the_cursor():
    async def check(app, pilot, fake):
        panels = _many(40)
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        app.draw({"sessions"})
        await pilot.pause(0.1)
        table = app.query_one("#sessions", DataTable)
        assert table.row_count == 40
        table.move_cursor(row=25)
        table.scroll_to(y=15, animate=False, immediate=True)
        await pilot.pause(0.1)
        y = table.scroll_y
        assert y > 0
        panels = _many(40, age0=60)  # every age moved, the same order: the cells change in place
        app.draw({"sessions"})
        await pilot.pause(0.2)
        assert (table.scroll_y, table.cursor_row) == (y, 25)
        assert table.get_row("s00xxxxxxx")[-2] == "1 min"  # its Last column
        rows = _many(40)["sessions"]["rows"]
        rows.insert(0, rows.pop(30))  # a new order: rebuilt, the cursor on its record, the scroll where it was
        rows[0]["age_s"] = 0
        panels = {**PANELS, "sessions": {"hours": 24, "rows": rows}}
        app.views["sessions"] = {**app.views["sessions"], "sort": "age"}
        app.draw({"sessions"})
        await pilot.pause(0.2)
        assert table.scroll_y == y and table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value == (
            "s25xxxxxxx")
    _run(check)


def test_pause_help_timezone_and_theme():
    async def check(app, pilot, fake):
        await pilot.press("space")
        assert app.paused and "PAUSED" in app.sub_title
        n = len(fake.calls)
        app.tick()
        await app.workers.wait_for_complete()
        assert len(fake.calls) == n  # paused: no read
        await pilot.press("r")  # r still reads now
        await app.workers.wait_for_complete()
        assert len(fake.calls) == n + 1 and fake.calls[-1] is True
        await pilot.press("space")
        assert not app.paused
        await pilot.press("5", "i")  # the focused panel's help
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui.PanelHelp) and app.screen.panel_name == "frontier"
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, tui.PanelHelp)
        queue = app.query_one("#queue")
        await pilot.click("#queue", offset=(4, 0))  # the top of its frame: the [i] of its title
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui.PanelHelp) and app.screen.panel_name == "queue"
        await pilot.press("i")
        await pilot.pause(0.1)
        await pilot.click("#queue", offset=(4, 3))  # a row: no help
        await pilot.pause(0.1)
        assert not isinstance(app.screen, tui.PanelHelp) and queue.row_count == 2
        await pilot.press("5", "t")
        assert app.settings["tz"] == "utc" and app.sub_title.endswith("| UTC")
        assert cockpit.load_state()["settings"]["tz"] == "utc"
        app.theme = "nord"  # picked in the command palette: the default one from now on
        await pilot.pause(0.1)
        assert cockpit.load_state()["settings"]["theme"] == "nord"
    _run(check)


def test_the_app_starts_with_its_settings():
    async def check(app, pilot, fake):
        assert app.theme == "gruvbox" and app.settings["tz"] == "utc" and "| UTC" in app.sub_title
    _run(check, settings={"theme": "gruvbox", "tz": "utc"})


def test_enter_opens_a_rows_detail_and_o_its_links(monkeypatch):
    opened = []
    monkeypatch.setattr(tui.detail, "open_link", lambda x: opened.append(x) or f"opened {x.get('url')}")

    async def check(app, pilot, fake):
        await pilot.press("5", "enter")  # the frontier's first row: wi-one
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, tui.DetailScreen) and screen.d["id"] == "wi-one" and screen.d["title"] == "First"
        screen.d["links"] = [{"label": "PR demo #1", "kind": "url", "url": "https://x/pull/1"},
                             {"label": "the item wi-two", "kind": "item", "id": "wi-two", "project": "demo"}]
        await pilot.press("5")  # the panels' keys are off under a detail
        assert app.screen is screen
        await pilot.press("o")  # two links: a list to pick from
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui.LinkScreen)
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert opened == [screen.d["links"][0]] and app.screen is screen
        app.open_link(screen.d["links"][1])  # another item: its detail on top
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui.DetailScreen) and app.screen.d["id"] == "wi-two"
        await pilot.press("escape", "escape")
        await pilot.pause(0.1)
        assert app.screen is app.screen_stack[0] and app.is_running
        await pilot.press("2", "enter")  # a queue entry without a project on this machine: its own fields
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui.DetailScreen) and app.screen.d["id"] == "ddr-b"
        assert app.screen.d["actions"] == [] and not app.screen.check_action("act", ("answer",))
    _run(check)


def _ddr_panels(root, ref):
    entry = {"id": ref, "kind": "decision", "source": "ddr", "unblocks": 0, "age_days": 0, "title": "Pick a layout",
             "since": "", "how": f"brain decision answer {ref} <option>"}
    return {**PANELS, "queue": {"projects": [{"project": "demo", "counts": {"decision": 1}, "entries": [entry]}]}}


def test_answering_a_decision_confirms_the_command_then_runs_it(tmp_path, monkeypatch):
    from brain import decisions, projects
    root = tmp_path / "demo"
    ddr, _ = decisions.ask(root, title="Pick a layout", question="Grid or tabs?", at="2026-11-02T10:00:00Z",
                           why="both", options=["Grid and tabs", "Tabs only"], project="demo")
    ran = []
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setattr(tui.detail, "run", lambda a, steps: ran.append((a.kind, steps)) or [
        {"command": tui.detail.shown(steps[0]), "exit": 0, "seconds": 0.1, "output": "answered"}])

    async def check(app, pilot, fake):
        fake.choices["demo"] = projects.Project("demo", root)
        panels = _ddr_panels(root, ddr["id"])
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        app.draw({"queue"})
        await pilot.press("2", "enter")
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui.DetailScreen) and [a.kind for a in app.screen.d["actions"]] == ["answer"]
        await pilot.press("a")
        await pilot.pause(0.1)
        answer = app.screen
        assert isinstance(answer, tui.AnswerScreen)
        await pilot.click("#ok")  # nothing picked: a warning, the dialog stays
        await pilot.pause(0.1)
        assert app.screen is answer
        answer.query(tui.RadioButton).last().value = True
        await pilot.pause(0.1)
        await pilot.click("#ok")
        await pilot.pause(0.1)
        confirm = app.screen
        assert isinstance(confirm, tui.ConfirmScreen) and confirm.steps == [
            ["brain", "--root", str(root), "decision", "answer", ddr["id"], "Tabs only", "--via", "tui", "--by",
             "Ada"]]
        await pilot.press("n")  # cancelled: nothing runs
        await pilot.pause(0.1)
        assert not ran and isinstance(app.screen, tui.DetailScreen)
        await pilot.press("a")
        await pilot.pause(0.1)
        app.screen.query(tui.RadioButton).first().value = True
        await pilot.pause(0.1)
        await pilot.click("#ok")
        await pilot.pause(0.1)
        await pilot.press("y")
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)
        assert ran == [("answer", [["brain", "--root", str(root), "decision", "answer", ddr["id"], "Grid and tabs",
                                    "--via", "tui", "--by", "Ada"]])]
        assert app.screen is app.screen_stack[0]  # done: back to the panels, read again
    _run(check)


def test_apply_shows_the_plan_then_runs_the_command_and_marks_it_done(tmp_path, monkeypatch):
    from brain import projects, queue
    root = tmp_path / "demo"
    ddr, _, _ = queue.add(root, kind="action", title="Apply the seed", what=r"Then .\install.ps1 -Apply.",
                          at="2026-11-02T10:00:00Z", project="demo")
    ran = []
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setattr(tui.detail, "run", lambda a, steps: ran.append((a.kind, steps)) or [
        {"command": tui.detail.shown(s), "exit": 0, "seconds": 0.1, "output": f"{a.kind} output"} for s in steps])
    handed = []
    monkeypatch.setattr(tui.handover, "prepare", lambda a, steps: handed.append((a.kind, steps)) or {"script": "h"})

    async def check(app, pilot, fake):
        fake.choices["demo"] = projects.Project("demo", root)
        entry = {"id": ddr["id"], "kind": "action", "source": "ddr", "unblocks": 0, "age_days": 0,
                 "title": "Apply the seed", "since": ""}
        panels = {**PANELS, "queue": {"projects": [{"project": "demo", "entries": [entry]}]}}
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        app.draw({"queue"})
        await pilot.press("2", "enter")
        await pilot.pause(0.1)
        assert [a.kind for a in app.screen.d["actions"]] == ["done", "apply"]
        await pilot.press("A")
        await pilot.pause(0.3)
        confirm = app.screen
        assert isinstance(confirm, tui.ConfirmScreen) and ran == [("plan", [[r".\install.ps1"]])]  # the plan first
        assert "plan output" in str(confirm.query_one("#plan", tui.Static).render())
        assert not confirm.query_one("#run", tui.Button).disabled
        await pilot.press("y")
        await pilot.pause(0.2)
        # an install.ps1 -Apply runs in the window once the cockpit has closed (INST-2), then the entry marked done
        assert len(ran) == 1 and handed == [("apply", [[r".\install.ps1", "-Apply"],
                                                       ["brain", "--root", str(root), "queue", "done", ddr["id"],
                                                        "--note", r"applied in brain tui: .\install.ps1 -Apply"]])]
        assert app.handover == {"script": "h"}
    _run(check)


def test_the_actions_are_refused_in_a_session_shell(tmp_path, monkeypatch):
    from brain import decisions, projects
    root = tmp_path / "demo"
    ddr, _ = decisions.ask(root, title="Pick", question="?", at="2026-11-02T10:00:00Z", why="x",
                           options=["A", "B"], project="demo")
    monkeypatch.setenv("CLAUDECODE", "1")

    async def check(app, pilot, fake):
        fake.choices["demo"] = projects.Project("demo", root)
        panels = _ddr_panels(root, ddr["id"])
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        app.draw({"queue"})
        await pilot.press("2", "enter")
        await pilot.pause(0.1)
        detail_screen = app.screen
        assert detail_screen.d["refused"] and "refused here" in str(detail_screen.query_one("#detail-foot").render())
        await pilot.press("a")
        await pilot.pause(0.1)
        assert app.screen is detail_screen  # refused: no answer dialog
    _run(check)


def test_the_title_shows_the_version_and_the_check_never_delays_the_first_paint(monkeypatch):
    """wi-brain-tui-update-check (UPD-1, UPD-2): the installed version at once, the newer one once the background
    check answers, u opens brain update's plan and nothing runs without the owner's y."""
    import threading
    gate, ran = threading.Event(), []
    mine = tui.update.__version__
    newer = {"installed": mine, "latest": "9.0.0", "newer": True, "repo": "RoJLD/brain", "pin": None,
             "checked": "2026-11-03T10:00:00Z", "source": "remote"}
    monkeypatch.setattr(tui.update, "check", lambda root=None, **kw: gate.wait(10) and newer)
    monkeypatch.setattr(tui.detail, "refused", lambda env=None: "")
    monkeypatch.setattr(tui.detail, "run", lambda a, steps: ran.append((a.kind, steps)) or [
        {"command": " ".join(steps[0]), "exit": 0, "seconds": 0.1, "output": "the plan"}])
    handed = []
    monkeypatch.setattr(tui.handover, "prepare", lambda a, steps: handed.append((a.label, steps)) or {"script": "h"})

    async def main():
        app = tui.CockpitApp(FakeCockpit(), refresh=2.0, probe=300)
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.pause(0.2)
            assert app.title == f"brain {mine}" and app.update_info is None  # drawn while the check still waits
            assert app.check_action("update", ()) is False  # u hidden: nothing newer known
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause(0.1)
            assert app.title == f"brain {mine} · 9.0.0 available" and app.check_action("update", ()) is True
            await pilot.press("u")
            await pilot.pause(0.3)
            confirm = app.screen
            assert isinstance(confirm, tui.ConfirmScreen) and confirm.steps == [["brain", "update", "--yes"]]
            assert ran == [("plan", [["brain", "update", "--check"]])]  # the plan shown, nothing installed
            await pilot.press("n")
            await pilot.pause(0.2)
            assert app.screen is app.screen_stack[0] and len(ran) == 1  # cancelled: never run on its own
            await pilot.press("u")
            await pilot.pause(0.3)
            await pilot.press("y")
            await pilot.pause(0.2)
            # the owner's y: handed over to the window (INST-2), never run inside the cockpit, which exits
            assert handed == [("Update", [["brain", "update", "--yes"]])] and len(ran) == 2
            assert app.handover == {"script": "h"}
    asyncio.run(main())


def _lagging(monkeypatch, installer="install.ps1"):
    """brain 0.2.1 installed, config.json engine.pin v0.2.3 (a pin PR merged, -Apply not run yet)."""
    info = {"installed": "0.2.1", "latest": "0.2.3", "newer": True, "repo": "RoJLD/brain", "pin": "v0.2.3",
            "lag": "behind", "installer": installer, "root": "/ada/brain", "checked": None, "source": "offline"}
    monkeypatch.setattr(tui.update, "check", lambda root=None, **kw: info)
    return info


def test_a_lagging_engine_opens_the_installers_plan_and_applies_on_yes_only(monkeypatch):
    """wi-brain-tui-apply-reload (INST-1, INST-2): the title bar says the pin to apply, u shows the brain's installer
    plan (without -Apply), n changes nothing, y hands -Apply over to the window that relaunches the cockpit."""
    _lagging(monkeypatch)
    ran, handed = [], []
    monkeypatch.setattr(tui.detail, "refused", lambda env=None: "")
    monkeypatch.setattr(tui.detail, "run", lambda a, steps: ran.append((a.kind, steps)) or [
        {"command": " ".join(steps[0]), "exit": 0, "seconds": 0.1, "output": "engine   ada/engine@v0.2.3"}])
    monkeypatch.setattr(tui.handover, "prepare", lambda a, steps: handed.append((a, steps)) or {"script": "h"})

    async def check(app, pilot, fake):
        assert app.title == "brain 0.2.1 · pin v0.2.3: -Apply" and app.check_action("update", ()) is True
        await pilot.press("u")
        await pilot.pause(0.3)
        confirm = app.screen
        assert isinstance(confirm, tui.ConfirmScreen) and confirm.steps == [["install.ps1", "-Apply"]]
        assert str(confirm.a.cwd) == str(tui.Path("/ada/brain")) and confirm.a.handover
        assert ran == [("plan", [["install.ps1"]])]  # the plan shown first, nothing applied
        assert "engine   ada/engine@v0.2.3" in str(confirm.query_one("#plan").render())
        await pilot.press("n")
        await pilot.pause(0.2)
        assert handed == [] and app.screen is app.screen_stack[0]  # no run without the owner's gesture
        await pilot.press("u")
        await pilot.pause(0.3)
        await pilot.press("y")
        await pilot.pause(0.2)
        assert [(a.label, a.ref, steps) for a, steps in handed] == [("Install", "pin v0.2.3", [["install.ps1", "-Apply"]])]
        assert ran == [("plan", [["install.ps1"]])] * 2  # -Apply never ran inside the cockpit
        assert app.handover == {"script": "h"}
    _run(check)


def test_the_install_is_refused_in_a_claude_code_session(monkeypatch):
    _lagging(monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(tui.detail, "run", lambda a, steps: pytest.fail("nothing runs, not even the plan"))
    monkeypatch.setattr(tui.handover, "prepare", lambda a, steps: pytest.fail("no handover"))

    async def check(app, pilot, fake):
        await pilot.press("u")
        await pilot.pause(0.2)
        assert app.screen is app.screen_stack[0] and app.handover is None  # refused: no confirmation at all
    _run(check)


def test_a_brain_without_an_installer_keeps_brain_update(monkeypatch):
    """The tester's brain: no installer of its own, so u is brain update's plan, through the same handover."""
    _lagging(monkeypatch, installer=None)
    monkeypatch.setattr(tui.detail, "refused", lambda env=None: "")
    monkeypatch.setattr(tui.detail, "run", lambda a, steps: [{"command": "x", "exit": 0, "seconds": 0, "output": ""}])

    async def check(app, pilot, fake):
        assert app.title == "brain 0.2.1 · 0.2.3 available"
        await pilot.press("u")
        await pilot.pause(0.3)
        assert app.screen.steps == [["brain", "update", "--yes"]] and app.screen.a.handover
    _run(check)


def test_run_starts_the_handover_once_the_app_is_gone(monkeypatch):
    started = []

    class App:
        def __init__(self, *a):
            self.handover = {"script": "h"}

        def run(self):
            started.append("app")

    monkeypatch.setattr(tui, "CockpitApp", App)
    monkeypatch.setattr(tui.handover, "start", lambda h: started.append(h) or 0)
    assert tui.run(FakeCockpit()) == 0 and started == ["app", {"script": "h"}]


def test_the_queue_panel_names_the_decisions_taken_by_default(monkeypatch):
    line = "Taken by default, to review: 2 (1 provisional) — brain decision defaulted"
    monkeypatch.setitem(PANELS, "queue", {**PANELS["queue"], "defaulted": line})

    async def check(app, pilot, fake):
        assert app.query_one("#queue").border_subtitle.startswith(escape(line))
    _run(check)
