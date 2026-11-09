"""wi-brain-tui-layout: the cockpit's tabs, the overview's cards and their keys (the Textual app; the data is
brain.cockpit's, tested in test_cockpit; the app's helpers are test_tui's)."""

from test_tui import GRID, PANELS, FakeCockpit, _ids, _many, _run, _session, _why  # skipped with it, without Textual
from textual.markup import escape
from textual.widgets import DataTable, Select, Static, Tabs

from brain import cockpit, tui


def _on_screen(app):
    """The panels and frames a tab shows."""
    return [n for n in tui.EVERY_FRAME if app.query_one(f"#{n}").display]


def _bar(app):
    return [str(t.label) for t in app.query("#tabs Tab")]


def test_a_tab_is_a_layout_of_the_same_panels():
    """wi-brain-tui-layout, UX-18: the keys and the bar go to a tab, each shows its panels and keeps their cursor; a tab
    not built yet says what brings it."""
    async def check(app, pilot, fake):
        assert app.tab == "overview" and app._view() == "grid" and set(_on_screen(app)) == set(cockpit.PANELS)
        assert _bar(app) == ["0 Overview", "1 Ada's queue", "2 Sessions 1!", "3 Frontier", "4 Milestones", "8 Health"]
        assert "What waits on me" in str(app.query_one("#question").render())
        await pilot.press("1")
        assert app.tab == "queue" and _on_screen(app) == ["queue"] and app.focused is app.query_one("#queue")
        assert app.query_one("#tabs", Tabs).active == "tab-queue"
        assert app.query_one("#queue").border_title.startswith(escape("demo > 1 Ada's queue"))  # alone: the breadcrumb
        assert app.check_action("toggle_max", ()) is False and app.check_action("next_view", ()) is False
        table = app.query_one("#queue", DataTable)
        table.move_cursor(row=1)
        await pilot.press("8")
        assert _on_screen(app) == ["alerts", "audit", "health", "exec"] and app.focused is app.query_one("#alerts")
        await pilot.press("m")  # several panels: a full view
        assert app.screen.maximized is app.query_one("#alerts")
        await pilot.press("escape")
        assert app.screen.maximized is None and app.tab == "health"
        await pilot.press("1")  # back: the same widget, its cursor where it was
        assert app.tab == "queue" and table.cursor_row == 1
        notified, notify = [], app.notify
        app.notify = lambda message, **kw: notified.append(message) or notify(message, **kw)
        await pilot.press("5", "comma")  # not built: said, nothing moves
        assert app.tab == "queue" and notified == ["Ideas is not here yet: it arrives with the ideas board",
                                                   "Settings is not here yet: it arrives with the settings pages"]
        await pilot.press("ctrl+pagedown")
        assert app.tab == "sessions"
        await pilot.press("ctrl+pageup", "ctrl+pageup", "ctrl+pageup")
        assert app.tab == "health"  # around the bar
        await pilot.click("#tab-frontier")
        await pilot.pause(0.1)
        assert app.tab == "frontier" and _on_screen(app) == ["frontier"] and app.focused is app.query_one("#frontier")
        await pilot.press("escape")  # back to the overview, where escape has nothing left to do
        assert app.tab == "overview" and app.check_action("back", ()) is False
    _run(check, tabs=GRID)


def test_the_views_of_a_tab_are_remembered_and_clicked():
    async def check(app, pilot, fake):
        assert app._view() == "cards" and _on_screen(app) == []  # UX-19: the default
        await pilot.press("v")
        assert app._view() == "grid" and len(_on_screen(app)) == 8
        state = cockpit.load_state()
        assert state["tab"] == "overview" and state["tabs"] == {"overview": {"view": "grid"}}
        assert "[Grid]" in str(app.query_one("#views").render())  # in words and brackets, never a colour alone
        await pilot.press("v")
        assert app._view() == "digest" and _on_screen(app) == ["digest"]
        await pilot.press("v")
        assert app._view() == "cards"
        views = app.query_one("#views", Static)
        await pilot.click(views, offset=(len("[Cards]  Grid  ") + 1, 0))  # its word: Digest
        await pilot.pause(0.1)
        assert app._view() == "digest"
        await pilot.click(views, offset=(views.region.width - 2, 0))  # its [i]
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui.PanelHelp) and app.screen.panel_name == "digest"
        await pilot.press("escape")
        await pilot.press("3")
        assert cockpit.load_state()["tab"] == "frontier"
    _run(check)


def test_the_app_starts_on_the_tab_and_view_it_is_given():
    async def check(app, pilot, fake):
        assert app.tab == "health" and _on_screen(app) == ["alerts", "audit", "health", "exec"]
        await pilot.press("0")
        assert app._view() == "digest"
    _run(check, tab="health", tabs={"overview": {"view": "digest"}})


def test_a_narrow_terminal_has_the_tabs_alone():
    """UX-2, spec §4.0.5: under 120 columns or 30 rows the bar's numbers, the active tab named, no grid; a resize lays it
    out again."""
    async def check(app, pilot, fake):
        assert app._view() == "cards" and _on_screen(app) == []
        assert _bar(app) == ["0 Overview", "1", "2", "3", "4", "8"]
        assert cockpit.tab_views("overview", app._narrow()) == ("cards", "digest")  # the grid is not offered
        await pilot.press("v", "v")
        assert app._view() == "cards"
        await pilot.press("2")
        assert _bar(app) == ["0", "1", "2 Sessions 1!", "3", "4", "8"]
        await pilot.press("8")
        assert app.query_one("#grid").has_class("stacked")
        await pilot.resize_terminal(160, 48)
        await pilot.pause(0.2)
        assert _bar(app)[1] == "1 Ada's queue" and not app.query_one("#grid").has_class("stacked")
        await pilot.press("0", "v")
        assert app._view() == "grid" and len(_on_screen(app)) == 8
        await pilot.press("3")  # the frontier, then a narrow terminal under the grid
        await pilot.press("0")
        await pilot.resize_terminal(100, 28)
        await pilot.pause(0.2)
        assert app._view() == "cards" and app.focused is app.query_one("#card-queue")  # the focus followed
    _run(check, size=(100, 40))


def test_the_bar_counts_what_each_tab_holds(monkeypatch):
    alerts = {"projects": [{"project": "demo", "counts": {"warn": 2}, "alerts": [
        {"level": "warn", "key": "a", "message": "m", "since": ""}, {"level": "warn", "key": "b", "message": "m",
                                                                     "since": ""}]}]}
    queue = {"projects": [{"project": "demo", "counts": {}, "entries": [
        {"id": "ddr-a", "kind": "decision", "unblocks": 1, "age_days": 0, "title": "x", "since": "", "band": "now"}]}]}

    async def check(app, pilot, fake):
        assert _bar(app) == ["0 Overview", "1 Ada's queue 1", "2 Sessions 1!", "3 Frontier", "4 Milestones", "8 Health 2"]
        assert "changed " in str(app.query_one("#status").render())  # the global bar: the last change, the next probe
    monkeypatch.setitem(PANELS, "alerts", alerts)
    monkeypatch.setitem(PANELS, "queue", queue)
    _run(check)


def test_escape_goes_back_one_step_at_a_time():
    """Spec §4.0.5: the search first, as a table's line says (« Escape clears the search »), then a full view, then the
    overview; each from the table as well as from the search field."""
    async def check(app, pilot, fake):
        await pilot.press("slash", *"nothing", "enter")  # kept: the focus back on the table
        assert app.search == "nothing" and app.focused is app.query_one("#sessions")
        assert "Escape clears the search" in _why(app, "frontier")
        app.query_one("#frontier").focus()
        await pilot.press("m")
        assert app.screen.maximized is app.query_one("#frontier") and app.check_action("back", ())
        await pilot.press("escape")  # the search
        assert app.search == "" and app.screen.maximized is app.query_one("#frontier")
        assert app.check_action("back", ())
        await pilot.press("escape")  # the full view
        assert app.screen.maximized is None and app.tab == "overview" and not app.check_action("back", ())
        await pilot.press("3", "escape")  # the tab
        assert app.tab == "overview"
    _run(check, tabs=GRID)


def test_a_key_shows_its_tab_at_once_so_the_next_key_starts_from_it():
    async def check(app, pilot, fake):
        app.action_tab("queue")
        app.action_tab("overview")  # two keys before any event of the bar arrives
        assert app.tab == "overview"
        await pilot.pause(0.2)
        assert app.tab == "overview" and app.query_one("#tabs", Tabs).active == "tab-overview"  # the stale event ignored
        app.action_next_tab()
        app.action_next_tab()
        await pilot.pause(0.2)
        assert app.tab == "sessions" and app.query_one("#tabs", Tabs).active == "tab-sessions"
    _run(check)


def test_a_click_on_the_bar_leaves_the_focus_on_the_body_and_its_tooltips_name_the_tabs():
    async def check(app, pilot, fake):
        await pilot.press("3")
        table = app.query_one("#frontier", DataTable)
        await pilot.click("#tab-frontier")  # the active tab: nothing moves
        await pilot.pause(0.1)
        assert app.focused is table
        await pilot.press("s")
        assert app.views["frontier"]["sort"] == "unblocks"  # its keys still work
        assert app.query_one("#tab-frontier").tooltip == "Frontier (3): What can start?"
        assert not app.query_one("#tabs").can_focus
    _run(check)


def test_each_tab_remembers_its_focus_and_its_panels_their_scroll():
    async def check(app, pilot, fake):
        panels = _many(70)
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        app.draw({"sessions"})
        await pilot.press("8")
        app.query_one("#audit").focus()
        await pilot.press("2")
        await pilot.pause(0.1)
        table = app.query_one("#sessions", DataTable)
        table.move_cursor(row=25)
        table.scroll_to(y=15, animate=False, immediate=True)
        await pilot.pause(0.1)
        y = table.scroll_y
        assert y > 0
        await pilot.press("8")
        assert app.focused is app.query_one("#audit") and app.last_panel == "audit"
        await pilot.press("2")
        await pilot.pause(0.1)
        assert (table.scroll_y, table.cursor_row) == (y, 25) and app.focused is table
        app.query_one("#scope").focus()  # its key again: the focus back on the body
        await pilot.press("2")
        await pilot.pause(0.1)
        assert app.focused is table
    _run(check)


def test_the_frames_of_the_health_tab():
    """The alerts on top, the three others side by side; stacked on a narrow terminal. The exec frame draws from the
    health panel: its lines, title and failed read."""
    health = {"projects": [{"project": "demo", "stacks": [], "code_index": []}],
              "exec": {"days": 7, "runs": 3, "failed": 1, "regressions": [],
                       "slowest": [{"project": "demo", "task": "sync", "runs": 3, "failed": 1, "median_s": 2.5,
                                    "max_s": 9}]}}

    def text(app, name):
        return str(app.query_one(f"#{name}-text").render())

    async def check(app, pilot, fake):
        await pilot.press("8")
        await pilot.pause(0.1)
        width = {n: app.query_one(f"#{n}").region.width for n in ("alerts", "audit", "health", "exec")}
        assert width["alerts"] == 160 and all(50 <= width[n] <= 54 for n in ("audit", "health", "exec"))
        assert app.query_one("#audit").region.y == app.query_one("#exec").region.y > app.query_one("#alerts").region.y
        assert "not probed yet" in text(app, "exec") or "probe" in text(app, "exec")  # no health panel yet
        snap = {"scope": "demo", "read_at": None, "probed_at": None, "panels": {**PANELS, "health": health},
                "errors": {"health": {"at": "2026-11-06T10:00:00Z", "error": "OSError: disk gone"}},
                "panel_at": {"health": "2026-11-06T09:58:00Z"}}
        fake.snapshot = lambda: snap
        app.settings["tz"] = "utc"
        app.draw({"health"})
        await pilot.pause(0.1)
        frame = app.query_one("#exec")
        assert frame.border_title == escape("8 Exec times (3 run(s) in 7 d, 1 failed) [i]")
        assert "2.5 s (max 9 s, 3 run(s), 1 failed) demo: sync" in text(app, "exec")
        assert frame.border_subtitle.startswith("read failed 10:00:00: OSError: disk gone; data of 09:58:00")
        await pilot.resize_terminal(100, 40)
        await pilot.pause(0.2)
        assert all(app.query_one(f"#{n}").region.width == 100 for n in width)  # stacked
    _run(check)


def test_the_bar_follows_the_panels():
    async def check(app, pilot, fake):
        assert _bar(app)[2] == "2 Sessions 1!"
        rows = [_session("a", "asking"), _session("b", "asking")]
        panels = {**PANELS, "sessions": {"hours": 24, "rows": rows}}
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        app._done({"sessions"}, "")
        await pilot.pause(0.1)
        assert _bar(app)[2] == "2 Sessions 2!"
    _run(check)


def test_a_view_or_a_narrow_terminal_closes_a_full_view_and_the_status_gives_way():
    async def check(app, pilot, fake):
        app.query_one("#queue").focus()
        await pilot.press("m")
        await pilot.press("v")  # another view: the full view closes
        assert app.screen.maximized is None and app._view() == "digest"
        await pilot.press("v", "v")
        await pilot.pause(0.1)
        assert app._view() == "grid"
        app.query_one("#queue").focus()
        await pilot.press("m")
        assert app.screen.maximized is app.query_one("#queue")
        await pilot.resize_terminal(100, 28)  # the grid gone, and the panel with it: never a blank screen
        await pilot.pause(0.2)
        assert app.screen.maximized is None and app._view() == "cards" and app.focused is app.query_one("#card-queue")
        assert app.query_one("#status").display
        await pilot.resize_terminal(80, 28)
        await pilot.pause(0.2)
        assert not app.query_one("#status").display and app.query_one("#search").region.width > 20
    _run(check, tabs=GRID)


def test_a_redraw_under_a_dialog_keeps_the_full_views_breadcrumb():
    async def check(app, pilot, fake):
        app.query_one("#queue").focus()
        await pilot.press("m", "i")
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui.PanelHelp)
        app.draw({"queue"})
        assert app.query_one("#queue").border_title.startswith(escape("demo > 1 "))
        await pilot.press("8")  # the tabs' keys are off under a dialog
        assert app.tab == "overview" and isinstance(app.screen, tui.PanelHelp)
    _run(check, tabs=GRID)


def _card_text(app, tab):
    return str(app.query_one(f"#card-{tab}").render())


NOW = {"projects": [{"project": "demo", "counts": {}, "entries": [
    {"id": "ddr-a", "kind": "decision", "band": "now", "unblocks": 1, "age_days": 0, "title": "Pick a layout", "since": ""},
    {"id": "ddr-b", "kind": "action", "band": "week", "unblocks": 4, "age_days": 2, "title": "Pick a theme", "since": ""}]}]}


def test_the_overview_opens_on_its_cards(monkeypatch):
    """UX-19: one card per tab, what counts in it, and the overview's own help."""
    monkeypatch.setitem(PANELS, "queue", NOW)

    async def check(app, pilot, fake):
        assert app._view() == "cards" and app.query_one("#cards").display and not app.query_one("#grid").display
        assert [c.tab_name for c in app.query(tui.Card)] == ["queue", "sessions", "milestones", "frontier", "health"]
        queue = app.query_one("#card-queue")
        assert app.focused is queue and queue.border_title == "1 Ada's queue · 1 now"
        assert "Pick a layout" in _card_text(app, "queue") and "Pick a theme" not in _card_text(app, "queue")
        assert "1 this week" in _card_text(app, "queue") and queue.border_subtitle == "Enter: the queue, band now"
        assert "! abcdef12: Task abcdef123456" in _card_text(app, "sessions")
        await pilot.press("i")  # the tab's own help: no panel on the screen
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui.PanelHelp) and app.screen.panel_name == "overview"
    _run(check)


def test_a_card_opens_its_tab_with_a_filter_never_saved(monkeypatch):
    monkeypatch.setitem(PANELS, "queue", NOW)

    async def check(app, pilot, fake):
        queue = app.query_one("#card-queue")
        await pilot.press("enter")
        table = app.query_one("#queue", DataTable)
        assert app.tab == "queue" and app.focused is table and _ids(app, "queue") == ["ddr-a"]
        assert table.border_subtitle.startswith("1 of 2 shown; band now")
        assert cockpit.load_state()["panels"]["queue"]["band"] == "all"  # never saved
        await pilot.press("s")  # a sort keeps the filter, and still does not save it
        assert app.views["queue"]["sort"] == "score" and _ids(app, "queue") == ["ddr-a"]
        assert cockpit.load_state()["panels"]["queue"] == {**cockpit.view_of("queue"), "sort": "score"}
        await pilot.press("escape")  # the tab left: the filter gone, the focus back on its card
        await pilot.pause(0.1)
        assert app.tab == "overview" and app.focused is queue and app.entered == {}
        assert len(_ids(app, "queue")) == 2
        await pilot.click("#card-frontier")  # a click, a card without a filter
        await pilot.pause(0.1)
        assert app.tab == "frontier" and app.entered == {} and app.focused is app.query_one("#frontier")
        assert not app.query_one("#cards").display and app.query_one("#grid").display
    _run(check)


def test_the_arrows_move_on_the_grid_of_cards():
    async def check(app, pilot, fake):
        order = ["queue", "sessions", "milestones", "frontier", "health"]  # three on the top row, two below

        def on(name):
            return app.focused is app.query_one(f"#card-{name}")
        assert order == [c.tab_name for c in app.query(tui.Card)] and on("queue")
        await pilot.press("up")  # past an edge: nothing
        assert on("queue")
        await pilot.press("left")
        assert on("queue")
        await pilot.press("right", "right")
        assert on("milestones")
        await pilot.press("right")  # the end of its row: it does not cross to the next
        assert on("milestones")
        await pilot.press("down")  # no card below: the last of the shorter row
        assert on("health")
        await pilot.press("down")  # no row below
        assert on("health")
        await pilot.press("right")  # no card to its right
        assert on("health")
        await pilot.press("left")
        assert on("frontier")
        await pilot.press("up")
        assert on("queue")
        await pilot.press("down", "right", "enter")  # the tab of the card reached, then back on that card
        assert app.tab == "health"
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert on("health")
    _run(check)


def test_a_key_moves_the_focus_at_once_so_the_next_key_goes_to_the_new_tab():
    async def check(app, pilot, fake):
        app.action_tab("queue")
        assert app.focused is app.query_one("#queue")  # in the same call, not at the next refresh
    _run(check)


def test_the_focus_comes_back_on_the_card_after_the_search_or_the_project_selector(monkeypatch):
    """No panel is on the screen with the cards: the search and the selector give the focus back to the card."""
    async def check(app, pilot, fake):
        card = app.query_one("#card-queue")
        await pilot.press("slash", *"x", "enter")
        assert app.focused is card and app.search == "x"
        await pilot.press("slash", "escape")
        await pilot.pause(0.1)
        assert app.focused is card and app.search == ""
        await pilot.press("p")
        app.query_one("#scope", Select).value = cockpit.ALL
        await pilot.pause(0.2)
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert app.focused is card
    _run(check)


def test_a_card_opens_all_its_rows_whatever_the_owners_filters_and_search(monkeypatch):
    """The card says « 1 now »: the owner's saved kind and a kept search hide nothing of it, and stay theirs."""
    monkeypatch.setitem(PANELS, "queue", NOW)

    async def check(app, pilot, fake):
        await pilot.press("slash", *"theme", "enter")
        assert app.search == "theme"
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert app.search == "" and _ids(app, "queue") == ["ddr-a"]
        assert app.views["queue"]["kind"] == "action" and cockpit.load_state()["panels"]["queue"]["kind"] == "action"
        await pilot.press("o")  # an order on the card's filter: the filter still not saved
        assert cockpit.load_state()["panels"]["queue"]["band"] == "all" and app.views["queue"]["reverse"]
        table = app.query_one("#queue", DataTable)
        band = next(c for c in table.ordered_columns if str(c.label) == "Band")
        table.post_message(DataTable.HeaderSelected(table, band.key, 0, band.label))  # a column title: the same
        await pilot.pause(0.1)
        assert cockpit.load_state()["panels"]["queue"]["band"] == "all"
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert _ids(app, "queue") == ["ddr-b"]  # the owner's kind again
    _run(check, views={"queue": {"kind": "action"}})


def test_the_focused_card_stays_in_sight():
    async def check(app, pilot, fake):
        await pilot.press("down", "down", "down", "down")
        await pilot.pause(0.2)
        health = app.query_one("#card-health")
        scroll = app.query_one("#cards")
        assert app.focused is health and scroll.scroll_y > 0
        await pilot.press("v", "v")  # the digest and back, the focus restored on its card
        await pilot.pause(0.3)
        body = scroll.region
        assert app.focused is health and health.region.y >= body.y and health.region.bottom <= body.bottom
    _run(check, size=(100, 25))


def test_the_cards_are_drawn_again_when_shown():
    async def check(app, pilot, fake):
        await pilot.press("2")
        rows = [_session("a", "asking"), _session("b", "asking")]
        panels = {**PANELS, "sessions": {"hours": 24, "rows": rows}}
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        await pilot.press("0")
        assert app.query_one("#card-sessions").border_title == "2 Sessions · 2 asking"
    _run(check)


def test_a_title_with_brackets_is_text_never_markup(monkeypatch):
    """« Move [/docs] out » crashed the cockpit (a closing tag of nothing), and « [blocking] » vanished from a cell."""
    panels = {"projects": [{"project": "demo", "counts": {}, "entries": [
        {"id": "ddr-a", "kind": "decision", "unblocks": 1, "age_days": 0, "title": "Move [/docs] out", "since": "",
         "blocking": True}]}]}
    monkeypatch.setitem(PANELS, "queue", panels)

    async def check(app, pilot, fake):
        await pilot.press("1")
        await pilot.pause(0.2)
        assert app.is_running
        text = "\n".join(s.text for s in app.screen._compositor.render_strips())
        assert "Move [/docs] out" in text and "ddr-a [blocking]" in text
        assert "Move [/docs] out" in _card_text(app, "queue")
    _run(check)


def test_the_filters_dialog_makes_a_cards_filter_the_owners(monkeypatch):
    monkeypatch.setitem(PANELS, "queue", NOW)

    async def check(app, pilot, fake):
        await pilot.press("enter", "f")
        await pilot.pause(0.1)
        dialog = app.screen
        assert isinstance(dialog, tui.ViewScreen) and dialog.query_one("#f-band", Select).value == "now"  # what is shown
        await pilot.press("escape")  # cancelled: still the card's
        await pilot.pause(0.1)
        assert app.entered == {"queue": {"kind": "all", "band": "now"}} and app.views["queue"]["band"] == "all"
        await pilot.press("f")
        await pilot.pause(0.1)
        await pilot.click("#apply")
        await pilot.pause(0.1)
        assert app.entered == {} and app.views["queue"]["band"] == "now"
        assert cockpit.load_state()["panels"]["queue"]["band"] == "now"
        await pilot.press("0", "1")  # the owner's now: it stays
        assert _ids(app, "queue") == ["ddr-a"]
    _run(check)


def test_the_cards_take_three_columns_or_one_on_a_narrow_terminal():
    async def check(app, pilot, fake):
        first, second = app.query_one("#card-queue"), app.query_one("#card-sessions")
        assert first.region.y == second.region.y and first.region.x < second.region.x
        assert app.query_one("#card-frontier").region.y > first.region.y
        await pilot.resize_terminal(100, 40)
        await pilot.pause(0.2)
        assert first.region.x == second.region.x and second.region.y > first.region.y
        assert first.region.width >= 90
        await pilot.press("down")
        assert app.focused is second
    _run(check)


def test_the_cards_follow_the_panels():
    async def check(app, pilot, fake):
        assert app.query_one("#card-sessions").border_title == "2 Sessions · 1 asking"
        rows = [_session("a", "asking"), _session("b", "asking")]
        panels = {**PANELS, "sessions": {"hours": 24, "rows": rows}}
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        app._done({"sessions"}, "")
        await pilot.pause(0.1)
        assert app.query_one("#card-sessions").border_title == "2 Sessions · 2 asking"
    _run(check)


def test_in_the_grid_open_alerts_take_a_whole_row(monkeypatch):
    """L11: their message reads in full; no alert, or once they are gone: the frame takes half a row, as the others."""
    alerts = {"projects": [{"project": "demo", "counts": {"warn": 1}, "alerts": [
        {"level": "warn", "key": "a", "message": "m", "since": ""}]}]}

    async def check(app, pilot, fake):
        await pilot.pause(0.1)
        frame = app.query_one("#alerts")
        assert not app.query_one("#grid").has_class("alerts-wide") and frame.region.width == 80
        panels = {**PANELS, "alerts": alerts}
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        app.draw({"alerts"})
        await pilot.pause(0.2)
        assert app.query_one("#grid").has_class("alerts-wide") and frame.region.width == 160
        # the row is whole and no cell left empty: the five rows hold the eight panels
        assert app.query_one("#digest").region.width == 80 and app.query_one("#health").region.y == (
            app.query_one("#digest").region.y)
        panels = PANELS
        app.draw({"alerts"})
        await pilot.pause(0.2)
        assert not app.query_one("#grid").has_class("alerts-wide") and frame.region.width == 80
    _run(check, tabs=GRID)


def test_the_digest_view_does_not_repeat_its_title():
    digest = {"projects": [{"project": "demo", "digest": "last-week", "written": False, "records": {"journals": []},
                            "text": "# Digest of demo\n\n## Items closed\n- wi-one\n"}]}

    async def check(app, pilot, fake):
        panels = {**PANELS, "digest": digest}
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        await pilot.press("v", "v")
        app.draw({"digest"})
        await pilot.pause(0.1)
        text = str(app.query_one("#digest-text").render())
        assert text.startswith("demo (last-week, built offline)") and "# Digest" not in text and "Items closed" in text
        assert app.query_one("#digest").border_title == escape("demo > 0 Digest [i]")
    _run(check)


def test_run_gives_the_app_its_tab_and_views(monkeypatch):
    seen = {}

    class App:
        handover = None

        def __init__(self, *a):
            seen["args"] = a

        def run(self):
            pass

    monkeypatch.setattr(tui, "CockpitApp", App)
    assert tui.run(FakeCockpit(), tab="health", tabs={"overview": {"view": "digest"}}) == 0
    assert seen["args"][-3:] == ("health", {"overview": {"view": "digest"}}, None)
