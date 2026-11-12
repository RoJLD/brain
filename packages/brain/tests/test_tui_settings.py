"""wi-brain-tui-settings: the cockpit's Settings tab (brain.tui_settings) in the Textual app; the settings as data are
test_settings'."""

from test_tui import _run  # skipped with it, without Textual
from test_tui_tabs import _bar, _on_screen
from textual.widgets import DataTable, Input, Select

from brain import cockpit, tui, tui_screens, tui_settings


def _settings(app):
    table = app.query_one("#settings-table", DataTable)
    return {str(table.get_row_at(i)[0]): str(table.get_row_at(i)[1]) for i in range(table.row_count)}


def _cursor_on(app, key):
    table = app.query_one("#settings-table", DataTable)
    table.move_cursor(row=[k.value for k in table.rows].index(key))


def test_the_settings_tab_edits_the_cockpit_and_only_names_the_brain_s_commands():
    """wi-brain-tui-settings: the comma opens the Settings tab, its pages on the left; Enter on a Cockpit setting edits it
    in tui.json and applies it now, a wrong value is refused; on a brain setting it says the command, nothing written."""
    async def check(app, pilot, fake):
        notified, notify = [], app.notify
        app.notify = lambda message, **kw: notified.append((kw.get("title"), message)) or notify(message, **kw)
        await pilot.press("comma")
        await pilot.pause(0.1)
        assert app.tab == "settings" and _on_screen(app) == ["settings"]
        assert app.focused is app.query_one("#settings-table")
        rows = _settings(app)
        assert rows["tz"] == "local" and rows["refresh"] == "2 s" and rows["titles.queue"] == "Ada's queue"
        _cursor_on(app, "tz")
        await pilot.press("enter")
        assert isinstance(app.screen, tui_screens.SettingScreen)
        app.screen.query_one("#setting-value", Select).value = "utc"
        await pilot.click("#save")
        await pilot.pause(0.1)
        assert app.settings["tz"] == "utc" and cockpit.load_state()["settings"]["tz"] == "utc"
        assert _settings(app)["tz"] == "utc" and app.sub_title.endswith("| UTC")
        _cursor_on(app, "refresh")
        await pilot.press("enter")
        app.screen.query_one("#setting-value", Input).value = "100ms"
        await pilot.press("enter")  # submitted: refused, nothing changes
        await pilot.pause(0.1)
        assert app.refresh_s == 2.0 and "refresh" not in cockpit.load_state()["settings"]
        assert ("refresh", "'100ms': 250 ms at least") in notified
        await pilot.press("enter")
        app.screen.query_one("#setting-value", Input).value = "5s"
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert app.refresh_s == 5.0 and cockpit.load_state()["settings"]["refresh"] == 5.0
        _cursor_on(app, "titles.queue")
        await pilot.press("enter")
        app.screen.query_one("#setting-value", Input).value = "Ma file"
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert cockpit.load_state()["settings"]["titles"] == {"queue": "Ma file"}
        assert "1 Ma file" in _bar(app)  # applied at once
        await pilot.press("enter")
        await pilot.click("#default")  # back to its default: the key removed
        await pilot.pause(0.1)
        assert "titles" not in cockpit.load_state()["settings"] and "1 Ada's queue" in _bar(app)
        await pilot.press("left", "down")  # the pages: Identity
        await pilot.pause(0.1)
        assert app.setting_page == "identity" and _settings(app)["identity.owner"] == "Ada"
        await pilot.press("right", "enter")  # a brain setting: its command said, no dialog, nothing written
        await pilot.pause(0.1)
        assert not isinstance(app.screen, tui_screens.SettingScreen)
        assert notified[-1][0] == "identity.owner: changed by" and "no brain config set" in notified[-1][1]
        assert app.check_action("columns", ()) is False  # C is a panel's table's, not the settings'
        await pilot.press("i")
        assert isinstance(app.screen, tui.PanelHelp) and app.screen.panel_name == "settings"
    _run(check)


def test_the_settings_frame_holds_the_pages_then_their_settings():
    async def check(app, pilot, fake):
        frame = app.query_one("#settings", tui_settings.SettingsFrame)
        pages = frame.query_one("#settings-pages", tui_settings.SettingsPages)
        assert pages.option_count == len(tui_settings.settings_.PAGES)
        assert [str(pages.get_option_at_index(i).prompt) for i in range(pages.option_count)] == [
            "Cockpit", "Identity", "Brain", "Permissions", "Setup"]
        assert app.check_action("edit_setting", ()) is False  # off the tab: its keys are off
        await pilot.press("comma")
        assert app.check_action("edit_setting", ()) is True
        table = app.query_one("#settings-table", DataTable)
        assert tuple(str(c.label) for c in table.ordered_columns) == tui_settings.SETTING_COLUMNS
        await pilot.press("left", "down", "down", "down", "down")  # the last page: Setup
        await pilot.pause(0.1)
        assert app.setting_page == "setup" and "checks" in _settings(app)
    _run(check)
