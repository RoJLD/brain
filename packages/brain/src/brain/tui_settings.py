"""The cockpit's Settings tab (``brain tui``, the comma; wi-brain-tui-settings, spec cockpit-ux §4.13 and
cockpit-ux-round2 §4.0.3): its pages on the left (brain.settings' ``PAGES``), the page's settings on the right with
their value, where each comes from and how it changes. Enter on a Cockpit setting opens its dialog
(tui_screens' SettingScreen): the value is checked (brain.settings.parse), saved to <BRAIN_HOME>/tui.json and applied at
once; on a brain setting it says the command that changes it, and nothing is written; on the Setup page it runs a
wizard (brain.wizards): its choice, a folder typed when it asks one, then its plan and its apply through the actions'
confirmation, each command logged as the owner's (wi-brain-tui-setup). The settings are read when the tab
shows, after an edit and on r: zero token, no probe.
"""

from __future__ import annotations

import time
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, OptionList

from . import cockpit, detail, wizards
from . import settings as settings_
from .tui_screens import AskScreen, ChoiceScreen, SettingScreen

SETTING_COLUMNS = ("Setting", "Value", "From", "Change")
SETTING_ACTIONS = ("edit_setting", "settings_pages", "settings_rows")


class SettingsTable(DataTable):
    """The settings of the page picked on the left (brain.settings): Enter edits a cockpit setting, else says the
    command that changes it; left goes back to the pages."""
    BINDINGS = [Binding("enter", "app.edit_setting", "Edit"), Binding("left", "app.settings_pages", "Pages")]


class SettingsPages(OptionList):
    """The Settings tab's pages: the cursor shows a page's settings, Enter or right goes to them."""
    BINDINGS = [Binding("right", "app.settings_rows", "Settings")]


class SettingsFrame(Horizontal):
    """The tab's one panel: the pages, then the page's settings."""
    DEFAULT_CSS = """
    #settings-pages { width: 22; height: 100%; border: none; }
    #settings-table { width: 1fr; height: 100%; }
    """

    def compose(self) -> ComposeResult:
        yield SettingsPages(*(settings_.page_label(p) for p in settings_.PAGES), id="settings-pages")
        yield SettingsTable(id="settings-table", zebra_stripes=True, cursor_type="row")


class SettingsTab:
    """The app's part of the Settings tab (mixed into brain.tui's CockpitApp)."""

    def _settings_init(self) -> None:
        self.setting_page = settings_.PAGES[0]  # the page shown
        self.setting_rows: dict[str, settings_.Setting] = {}  # its settings by key

    def _settings_allows(self) -> bool:
        return len(self.screen_stack) == 1 and self.tab == "settings"

    def _draw_settings(self) -> None:
        """The page's settings, read again (zero token, no probe); the cursor kept on its setting."""
        if self.tab != "settings":
            return  # not on screen: read when shown
        state = {"scope": self.scope, "settings": self.settings}
        rows = settings_.collect(getattr(self.cockpit, "root", None), state, tuple(sorted(self.available_themes)),
                                 pages=(self.setting_page,),
                                 running={"refresh": self.refresh_s, "probe": self.probe_s})[self.setting_page]
        self.setting_rows = {s.key: s for s in rows}
        table = self._q("#settings-table", DataTable)
        if not table.columns:
            table.add_columns(*SETTING_COLUMNS)
        keep = None
        if table.row_count:
            try:
                keep = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            except Exception:  # the cursor out of the rows
                keep = None
        table.clear()
        for s in rows:
            table.add_row(Text(s.key, style="bold" if s.edit else ""), Text(s.value), Text(s.source), Text(s.change),
                          key=s.key)
        keys = [s.key for s in rows]
        if keep in keys:
            table.move_cursor(row=keys.index(keep), scroll=False)
        pages = self._q("#settings-pages", OptionList)
        for i, page in enumerate(settings_.PAGES):  # their words in the language now
            if str(pages.get_option_at_index(i).prompt) != settings_.page_label(page):
                pages.replace_option_prompt_at_index(i, settings_.page_label(page))
        if pages.highlighted != settings_.PAGES.index(self.setting_page):
            pages.highlighted = settings_.PAGES.index(self.setting_page)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "settings-pages" and event.option_index is not None:
            page = settings_.PAGES[event.option_index]
            if page != self.setting_page:
                self.setting_page = page
                self._draw_settings()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "settings-pages":
            self.action_settings_rows()

    def action_settings_rows(self) -> None:
        self._q("#settings-table").focus()

    def action_settings_pages(self) -> None:
        self._q("#settings-pages").focus()

    def action_edit_setting(self) -> None:
        """Enter on a setting: a cockpit setting's dialog; a brain setting's command, said (never run from here)."""
        table = self._q("#settings-table", DataTable)
        if not table.row_count:
            return
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        s = self.setting_rows.get(key)
        if s is None:
            return
        if not s.edit:
            self.notify(s.change, title=f"{s.key}: changed by", timeout=10)
        elif s.edit == "wizard":
            self.start_wizard(s.key)
        else:
            self.push_screen(SettingScreen(s, s.value), lambda got: self.set_setting(s, got[1]) if got else None)

    # --- the Setup page's wizards (brain.wizards): a choice, a word typed, then the plan and the apply ---

    def start_wizard(self, wid: str) -> None:
        """A wizard: its choice first when it has one, then the folder it asks for, then its commands' confirmation
        (brain.tui's start_action: the plan run and shown, then the apply on the owner's yes, logged; refused in a
        Claude Code session's shell)."""
        w = wizards.by_id(getattr(self.cockpit, "root", None)).get(wid)
        if w is None:
            return
        if w.choices:
            labels = [c or "its steps" for c in w.choices]
            self.push_screen(ChoiceScreen(w.title, labels),
                             lambda i: self._wizard_ask(w, w.choices[i]) if i is not None else None)
        elif w.plan and "{choice}" in w.plan:
            self.notify("nothing to choose from on this machine", title=w.title, severity="warning")
        else:
            self._wizard_ask(w, "")

    def _wizard_ask(self, w, choice: str) -> None:
        if w.ask:
            self.push_screen(AskScreen(w.title, w.ask),
                             lambda typed: self._wizard_folder(w, choice, typed) if typed else None)
        else:
            self._wizard_run(w, choice, "")

    def _wizard_folder(self, w, choice: str, typed: str) -> None:
        try:
            folder = wizards.folder(typed)
        except ValueError as exc:  # a word that is not a folder (an option, a relative path): nothing runs
            self.notify(str(exc), title=w.title, severity="error")
            return
        self._wizard_run(w, choice, folder)

    def _wizard_run(self, w, choice: str, typed: str) -> None:
        project = self.scope if self.scope != cockpit.ALL and "," not in self.scope else ""
        plan, apply = w.words("plan", choice, typed, project), w.words("apply", choice, typed, project)
        notes = [w.what, *w.notes] + ([f"Yours, in your own terminal: {w.owner}."] if w.owner else [])
        cwd = getattr(self.cockpit, "root", None) or Path.cwd()
        self.start_action(detail.Action(kind="apply", label=w.title, project=project or "brain", ref=w.id,
                                        cwd=Path(cwd), steps=[apply or plan], preview=plan if apply else None,
                                        plan=notes, gated=True))

    def _is_set(self, key: str) -> bool:
        if key.startswith("titles."):
            return key.split(".", 1)[1] in (self.settings.get("titles") or {})
        return key in self.settings

    def set_setting(self, s: settings_.Setting, text: str) -> None:
        """A cockpit setting from its dialog: checked, saved to tui.json and applied now ('' sets its default). A
        setting not set and saved as the default it shows stays unset: a later default (a language, a name) applies."""
        if not self._is_set(s.key) and text.strip() == s.value:
            return
        try:
            value = settings_.parse(s.key, text, s.choices)
        except ValueError as exc:
            self.notify(str(exc), title=s.key, severity="error")
            return
        self.settings = {"tz": "local", **settings_.edited(self.settings, s.key, value)}
        saved = self._save()  # first: the language and the titles are read from tui.json (cockpit.settings)
        if s.key == "theme":
            self.theme = self.settings.get("theme") or s.default
        elif s.key == "refresh":
            self.refresh_s = self.settings.get("refresh") or cockpit.REFRESH_S
            self._restart_timer()
        elif s.key == "probe":
            self.probe_s = self.settings.get("probe") or cockpit.PROBE_S
            self.next_probe = time.monotonic() + self.probe_s
        self._subtitle()
        self._layout()  # the titles, the bar and the language; the settings read again
        self.draw(set(cockpit.PANELS))  # the times in the timezone, the titles
        shown = self.setting_rows.get(s.key)
        if saved:
            self.notify(f"{s.key}: {shown.value if shown else text}", title="saved to tui.json")
        else:  # a newer brain's tui.json, or a write that failed: applied for this launch, not remembered
            self.notify(f"{s.key}: applied until the cockpit closes, not saved: "
                        f"{cockpit.state_refusal() or 'tui.json could not be written'}", title=s.key, severity="error")

    def _restart_timer(self) -> None:
        if self.timer is not None:
            self.timer.stop()
        self.timer = self.set_interval(self.refresh_s, self.tick)
