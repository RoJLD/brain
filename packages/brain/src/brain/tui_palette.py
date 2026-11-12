"""The cockpit's command palette and column chooser (``brain tui``, wi-brain-tui-layout; spec 2026-11-02 cockpit-ux §4.4):
ctrl+p reaches every tab, view, project, sort and filter without learning a key (brain.cockpit's ``palette``, data tested
without Textual), and ``C`` chooses a table's columns: shown or hidden, their order, the longest a title may be. A mixin of
brain.tui's CockpitApp.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import partial

from rich.text import Text
from textual.app import SystemCommand
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Select

from . import cockpit
from .tui_screens import ColumnsScreen


STYLES = {"sessions": {"asking": "bold magenta", "running": "green", "stale": "yellow", "idle": "cyan", "ended": "dim"},
          "alerts": {"critical": "bold red", "error": "red", "warn": "yellow", "info": "dim"}}
STYLE_COLUMN = {"sessions": "State", "alerts": "Level"}  # the column those words are in, wherever it is chosen to be
MASTER_STYLES = {70: "yellow", 80: "bold dark_orange", 90: "bold red"}  # a master's row at each step (ST-4)


def styled(name: str, r: dict, cols: tuple, cells: tuple) -> tuple:
    """A row's cells as text, never markup (« [/docs] »): the state's or level's colour on its word; every other cell of a
    master's row past 70, 80, 90 % of its budget in that step's."""
    word = STYLE_COLUMN.get(name)
    step = MASTER_STYLES.get(r.get("ctx_step"), "") if name == "sessions" else ""
    styles = STYLES.get(name, {})  # a plugin's panel: no colour of its own
    return tuple(Text(str(cell), style=styles.get(cell, "") if c == word else step) for c, cell in zip(cols, cells))


def same_cell(new, old) -> bool:
    """Two cells show the same: a Text's equality leaves out its style, and a master's row changes colour at each step."""
    return new == old and getattr(new, "style", "") == getattr(old, "style", "")


class PaletteAndColumns:
    """The palette's entries and what they do, and the columns each table shows."""

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        if isinstance(screen, ModalScreen):  # a dialog is open: the panels' keys are off, and so are their entries
            return
        for entry in cockpit.palette(self.cockpit.choices, self._narrow()):
            title = entry["title"].replace("[", "\\[")  # the palette reads it as markup: a title or a project's name is text
            yield SystemCommand(title, entry["help"], partial(self.palette_do, *entry["do"]))

    def palette_do(self, what: str, *args) -> None:
        {"tab": self.action_tab, "view": self._palette_view, "scope": self._palette_scope, "sort": self._palette_sort,
         "filter": self._palette_filter, "columns": self._palette_columns, "reset": self._palette_reset}[what](*args)

    def _palette_view(self, tab: str, view: str) -> None:
        self.action_tab(tab)
        self.action_set_view(view)

    def _palette_scope(self, value: str) -> None:
        self._q("#scope", Select).value = value  # as a pick in the selector: on_select_changed

    def _palette_sort(self, name: str, key: str) -> None:
        self.action_tab(cockpit.panel_tab(name))
        self._set_view(name, {**self.views[name], "sort": key, "reverse": False})

    def _palette_filter(self, name: str, field: str, value: str) -> None:
        self.action_tab(cockpit.panel_tab(name))
        self.entered.pop(name, None)
        self._set_view(name, {**self.views[name], field: value})

    def _palette_columns(self, name: str) -> None:
        self.action_tab(cockpit.panel_tab(name))
        self.action_columns(name)

    def _palette_reset(self) -> None:
        """Every view, sort, filter and column back to its default; the scope, the theme and the timezone stay."""
        self.views = {n: cockpit.view_of(n) for n in cockpit.SORTS}
        self.chosen, self.entered, self.tab_views = {}, {}, {}
        self._save()
        for name in cockpit.COLUMNS:
            self._rebuild_columns(name)
        self._layout()
        self._focus_body()

    def action_columns(self, name: str | None = None) -> None:
        """A table's column chooser: the focused table's, or the one the palette names."""
        name = name or self.focused.id
        self.push_screen(ColumnsScreen(name, self.chosen.get(name)), lambda chosen: self._chosen_columns(name, chosen))

    def _chosen_columns(self, name: str, chosen: dict | None) -> None:
        if chosen is None:  # cancelled
            return
        if chosen:
            self.chosen[name] = chosen
        else:  # reset: the defaults
            self.chosen.pop(name, None)
        self._save()
        self._rebuild_columns(name)

    def _rebuild_columns(self, name: str) -> None:
        """A table with its new columns, the cursor on the record it was on."""
        table = self._q(f"#{name}", DataTable)
        key = self._side_row(name)
        self._set_columns(name)
        self.draw({name})
        if key is not None and key in table.rows:
            table.move_cursor(row=table.get_row_index(key))

    def _set_columns(self, name: str) -> None:
        table = self._q(f"#{name}", DataTable)
        table.clear(columns=True)
        table.add_columns(*cockpit.columns(name, self.multi is not False, self.chosen.get(name)))
