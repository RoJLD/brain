"""wi-brain-tui-layout: the column chooser and the palette (brain.tui_palette, the Textual app; test_tui has the helpers)."""

from test_tui import OVER, PANELS, _run, _session
from textual.command import CommandPalette
from textual.widgets import Button, DataTable, Select, SelectionList

from brain import cockpit, tui, tui_screens


def _labels(app, name):
    return [str(c.label) for c in app.query_one(f"#{name}", DataTable).ordered_columns]


def _still(fake):
    fake.refresh = lambda probe=False: set()


def _command(app, title):
    return next(c for c in app.get_system_commands(app.screen) if c.title == title)


def test_c_chooses_a_tables_columns_and_they_are_remembered():
    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3")
        assert app.check_action("columns", ())
        before = _labels(app, "frontier")  # one project: its table has no Project column, the chooser has
        await pilot.press("C")
        await pilot.pause(0.1)
        dialog = app.screen
        assert isinstance(dialog, tui_screens.ColumnsScreen)
        chooser = dialog.query_one("#column-list", SelectionList)
        every = list(cockpit.columns("frontier"))
        assert list(chooser.selected) == every and "Project" in every and "Project" not in before
        chooser.highlighted = 0
        await pilot.press("space")  # hide the first: P
        await pilot.pause(0.1)
        await pilot.click("#apply")
        await pilot.pause(0.2)
        assert app.screen is app.screen_stack[0]
        assert _labels(app, "frontier") == before[1:] and "P" not in _labels(app, "frontier")
        assert app.query_one("#frontier", DataTable).row_count == 3  # the rows drawn again
        assert cockpit.load_state()["columns"]["frontier"]["shown"] == every[1:]
        await pilot.press("C")  # Escape changes nothing
        await pilot.pause(0.1)
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert _labels(app, "frontier") == before[1:]
        await pilot.press("C")  # Reset: the defaults
        await pilot.pause(0.1)
        await pilot.click("#reset")
        await pilot.pause(0.2)
        assert _labels(app, "frontier") == before and "columns" not in cockpit.load_state()
    _run(check, size=OVER)


def test_up_and_down_move_a_column_and_its_cursor_with_it():
    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3", "C")
        await pilot.pause(0.1)
        dialog = app.screen
        chooser = dialog.query_one("#column-list", SelectionList)
        order = list(dialog.order)
        chooser.highlighted = 1
        await pilot.press("shift+up")
        await pilot.pause(0.1)
        assert dialog.order == [order[1], order[0], *order[2:]] and chooser.highlighted == 0
        await pilot.press("shift+up")  # past the top: nothing
        assert dialog.order[0] == order[1]
        await pilot.press("shift+down")
        await pilot.pause(0.1)
        assert dialog.order == order and chooser.highlighted == 1
        dialog.query_one("#down", Button).press()
        await pilot.pause(0.1)
        assert dialog.order[2] == order[1] and chooser.highlighted == 2
        dialog.query_one("#up", Button).press()
        await pilot.pause(0.1)
        assert dialog.order == order and list(chooser.selected) == order  # what is shown stays shown
        chooser.highlighted = len(order) - 1
        await pilot.press("shift+down")  # past the bottom: nothing
        assert dialog.order == order
        dialog.query_one("#title-width", Select).value = 40
        chooser.highlighted = 2  # Unblocks, after P and Project
        dialog.query_one("#down", Button).press()
        await pilot.pause(0.1)
        await pilot.click("#apply")
        await pilot.pause(0.2)
        assert _labels(app, "frontier")[:3] == ["P", order[3], order[2]]
        assert app.chosen["frontier"]["width"] == 40 and app.chosen["frontier"]["shown"][:2] == ["P", "Project"]
    _run(check, size=OVER)


def test_a_title_is_cut_and_a_hidden_columns_line_finds_a_place():
    long = {"id": "wi-long", "priority": "P1", "milestone": "", "unblocks": 0, "age_days": 1, "since": "",
            "title": "A title much longer than the width the owner chose for it"}

    async def check(app, pilot, fake):
        _still(fake)
        panels = {**PANELS, "frontier": {"projects": [{"project": "demo", "items": [long]}]}}
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        app.draw({"frontier"})
        await pilot.press("3")
        table = app.query_one("#frontier", DataTable)
        title = _labels(app, "frontier").index("Title")
        assert str(table.get_row_at(0)[title]).endswith("…") and len(str(table.get_row_at(0)[title])) == 20
        panels = {**PANELS, "frontier": {"projects": [{"project": "demo", "items": []}]}}
        app.draw({"frontier"})
        await pilot.pause(0.1)
        row = [str(c) for c in table.get_row_at(0)]
        assert "No startable item" in row[title]  # a line that says why is never cut
        app.chosen["frontier"] = {"shown": ["P", "Id"], "width": 0}
        app._set_columns("frontier")
        app.draw({"frontier"})
        await pilot.pause(0.1)
        assert [str(c) for c in table.get_row_at(0)][0].startswith("No startable item")  # its column hidden: the first
    _run(check, size=OVER, columns={"frontier": {"shown": [], "width": 20}})


def test_the_chosen_columns_and_the_state_colour_follow_a_new_order():
    rows = [{**_session("abcdef123456", "asking"), "cost_usd": 3.0, "ctx_step": 80}]

    async def check(app, pilot, fake):
        _still(fake)
        panels = {**PANELS, "sessions": {"hours": 24, "rows": rows}}
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        app.draw({"sessions"})
        await pilot.press("2")
        table = app.query_one("#sessions", DataTable)
        assert _labels(app, "sessions") == ["Title", "State", "Cost"]
        title, state, cost = table.get_row_at(0)
        assert (str(title), str(state), str(cost)) == ("Task abcdef123456", "asking", "$3.00")
        assert state.style == "bold magenta" and title.style == tui.MASTER_STYLES[80]  # its word's colour, wherever it is
        cost_column = next(c for c in table.ordered_columns if str(c.label) == "Cost")
        table.post_message(DataTable.HeaderSelected(table, cost_column.key, 2, cost_column.label))  # a title sorts
        await pilot.pause(0.1)
        assert app.views["sessions"]["sort"] == "cost"
    _run(check, size=OVER, columns={"sessions": {"shown": ["Title", "State", "Cost"], "width": 0}})


def test_a_scope_with_several_projects_keeps_the_chosen_columns():
    async def check(app, pilot, fake):
        _still(fake)
        assert _labels(app, "frontier") == ["Id", "Title"]  # one project: Project left out
        app.query_one("#scope", Select).value = cockpit.ALL
        await pilot.pause(0.2)
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)
        assert _labels(app, "frontier") == ["Id", "Project", "Title"] and app.multi
    _run(check, size=OVER, columns={"frontier": {"shown": ["Id", "Project", "Title"], "width": 0}})


def test_no_table_no_columns_key_and_a_panel_without_a_view_has_one():
    async def check(app, pilot, fake):
        _still(fake)
        assert not app.check_action("columns", ())  # the cards
        await pilot.press("C")
        await pilot.pause(0.1)
        assert app.screen is app.screen_stack[0]
        await pilot.press("8")  # the alerts: a table without a view
        await pilot.pause(0.1)
        assert app.focused is app.query_one("#alerts") and app.check_action("columns", ())
        await pilot.press("C")
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui_screens.ColumnsScreen) and app.screen.panel_name == "alerts"
        assert not app.check_action("columns", ())  # the panels' keys are off under a dialog
        await pilot.press("escape")
        await pilot.pause(0.1)
        app.query_one("#audit").focus()
        await pilot.pause(0.1)
        assert not app.check_action("columns", ())  # a frame of text
    _run(check, size=OVER)


def test_the_palette_goes_to_a_tab_for_real():
    async def check(app, pilot, fake):
        _still(fake)
        app.action_command_palette()
        await pilot.pause(0.2)
        assert isinstance(app.screen, CommandPalette)
        await pilot.press(*"go to frontier")
        await pilot.pause(0.5)
        await pilot.press("down", "enter")
        await pilot.pause(0.3)
        assert app.screen is app.screen_stack[0] and app.tab == "frontier"
    _run(check, size=OVER)


def test_the_palettes_entries_do_what_they_say():
    async def check(app, pilot, fake):
        _still(fake)
        _command(app, "Overview: the Grid view").callback()
        await pilot.pause(0.1)
        assert app.tab == "overview" and app._view() == "grid"
        _command(app, "Go to Health").callback()
        await pilot.pause(0.1)
        assert app.tab == "health"
        _command(app, "Frontier: sort by unblocks").callback()  # its tab, its sort
        await pilot.pause(0.1)
        assert app.tab == "frontier" and app.views["frontier"]["sort"] == "unblocks"
        _command(app, f"{cockpit.title('queue')}: kind decision").callback()
        await pilot.pause(0.1)
        assert app.tab == "queue" and app.views["queue"]["kind"] == "decision"
        assert cockpit.load_state()["panels"]["queue"]["kind"] == "decision"
        _command(app, "Sessions: choose its columns").callback()
        await pilot.pause(0.1)
        assert app.tab == "sessions" and isinstance(app.screen, tui_screens.ColumnsScreen)
        assert app.screen.panel_name == "sessions"
        assert not any(c.title == "Go to Health" for c in app.get_system_commands(app.screen))  # none under a dialog
        await pilot.press("escape")
        await pilot.pause(0.1)
        _command(app, "Project: global: every project").callback()
        await pilot.pause(0.2)
        await app.workers.wait_for_complete()
        assert fake.selected == ["all"]
    _run(check, size=OVER)


def test_reset_the_views_keeps_the_project_and_the_theme():
    async def check(app, pilot, fake):
        _still(fake)
        app.entered = {"queue": {"band": "now"}}
        _command(app, "Reset the views").callback()
        await pilot.pause(0.2)
        assert app.views == {n: cockpit.view_of(n) for n in cockpit.SORTS} and app.entered == {} and app.chosen == {}
        assert app.tab_views == {} and app._view() == "list"  # the frontier stays on screen
        assert app.focused is app.query_one("#frontier")
        assert _labels(app, "frontier")[0] == "P" and app.settings["theme"] == "nord" and app.scope == "demo"
        state = cockpit.load_state()
        assert state["panels"]["frontier"]["sort"] == "priority" and "columns" not in state and state["tabs"] == {}
        assert state["settings"]["theme"] == "nord"
    _run(check, size=OVER, tab="frontier", views={"frontier": {"sort": "age"}}, settings={"theme": "nord"},
         tabs={"overview": {"view": "grid"}}, columns={"frontier": {"shown": ["Id"], "width": 0}})
