"""The detail beside the list (``brain tui``, wi-brain-tui-layout, UX-20; spec 2026-11-03 cockpit-ux-round2 §4.0.2 and §10):
from 140 columns, on a tab that is one list (brain.cockpit's ``detail_beside``), a row's detail sits right of the list and
follows the cursor. Narrower, or on a tab of several panels, Enter opens it over them as before (tui_screens' DetailScreen).

Following costs nothing the cockpit can feel: it reads once the cursor rests (``FOLLOW_S``, so an arrow held down reads
nothing), in a worker thread (a spec's section is a file), and remembers each row's detail until its panel changes. A read
that its panel's change overtook is thrown away, and a detail that could not be read is not remembered.

Enter on the list gives it the focus, where it scrolls and o opens a link; Escape gives the focus back. a, d and A act on
the row from the list or from it, each after the same confirmation as in the dialog, and only once the pane shows the row
under the cursor: never the one it left.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.content import Content
from textual.widgets import DataTable, Label, Static

from . import cockpit, detail
from .tui_screens import detail_foot, detail_lines

FOLLOW_S = 0.12  # the cursor at rest this long: the row's detail is read
NO_ROW = "No row here: the list says why."


class DetailPane(Vertical):
    """The row's detail, beside the list: its title, its lines, its links and actions; o opens a link, Escape goes back."""
    BINDINGS = [Binding("escape", "app.side_back", "Back to the list"), Binding("o", "app.side_open", "Open")]

    def compose(self) -> ComposeResult:
        yield Label(id="side-title")
        yield VerticalScroll(id="side-body")
        yield Static(id="side-foot")


class DetailBeside:
    """What the app does for its pane: which tab has one, and following the cursor. A mixin of brain.tui's CockpitApp."""

    def _side_init(self) -> None:
        self.beside = False  # the pane is on the screen
        self.side_d: dict | None = None  # the detail shown
        self.side_at: tuple | None = None  # (panel, row key) it shows
        self.side_cache: dict[tuple, dict] = {}  # each row's detail, until its panel changes
        self.side_seq = 0  # the last read asked: an older one's answer is kept, not shown
        self.side_gen: dict[str, int] = {}  # each panel's changes: a read its panel's change overtook is thrown away
        self.side_timer = None

    def _side_list(self) -> str | None:
        """The list the pane follows: the one panel of the tab's view; None when the tab has no pane."""
        return cockpit.tab_panels(self.tab, self._view())[0] if self.beside else None

    def _side_layout(self, view: str) -> None:
        """The pane on the screen or not, for this tab, this view and this width; the row's detail read if it is."""
        self.beside = cockpit.detail_beside(self.tab, view, self.size.width)
        self._q("#side").display = self.beside
        if self.beside:
            self._side_follow()

    def _side_follow(self) -> None:
        """Read the row under the cursor once it rests: a new move starts the wait again."""
        if self.side_timer is not None:
            self.side_timer.stop()
        self.side_timer = self.set_timer(FOLLOW_S, self._side_read)

    def _side_read(self) -> None:
        """The row under the cursor: from what is remembered, else read in a worker thread."""
        if self.side_timer is not None:
            self.side_timer.stop()
        self.side_timer = None
        name = self._side_list() if self.screen_stack else None  # no screen: the app is closing
        if name is None:
            return
        key = self._side_row(name)
        row = self.records.get(name, {}).get(key)
        self.side_seq += 1
        if row is None:
            self._side_show(None, None)
        elif (name, key) in self.side_cache:
            self._side_show((name, key), self.side_cache[(name, key)])
        else:
            seq, gen = self.side_seq, self.side_gen.get(name, 0)
            self.run_worker(lambda: self._side_thread(seq, gen, name, key, row), thread=True, group="side",
                            exit_on_error=False)

    def _side_row(self, name: str) -> str | None:
        table = self._q(f"#{name}", DataTable)
        if not table.is_valid_coordinate(table.cursor_coordinate):  # no row yet
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    def _side_thread(self, seq: int, gen: int, name: str, key: str, row: dict) -> None:
        keep = True
        try:
            d = detail.of(name, row, self.cockpit)
        except Exception as exc:  # a detail that cannot be read is said there, never a crash, and read again next time
            keep = False
            d = {"panel": name, "id": key, "title": f"{type(exc).__name__}: {exc}", "sections": [], "links": [],
                 "actions": [], "refused": ""}
        self.call_from_thread(self._side_done, seq, gen, (name, key), d, keep)

    def _side_done(self, seq: int, gen: int, at: tuple, d: dict, keep: bool = True) -> None:
        if gen != self.side_gen.get(at[0], 0):  # its panel changed during the read: what it says is old, a new read follows
            return
        if keep:
            self.side_cache[at] = d
        if seq == self.side_seq and self.screen_stack:  # no screen: the app is closing
            self._side_show(at, d)

    def _side_show(self, at: tuple | None, d: dict | None) -> None:
        """Its lines replaced when they changed: the same detail keeps its scroll, another row starts at its top."""
        if at == self.side_at and d == self.side_d and at is not None:
            return
        moved, self.side_at, self.side_d = at != self.side_at, at, d
        body = self._q("#side-body", VerticalScroll)
        with self.batch_update():
            body.remove_children()
            body.mount_all(detail_lines(d) if d else [Static(Text(NO_ROW, style="italic"), classes="line")])
            self._q("#side-title", Label).update(Content(d["title"] if d else ""))
            self._q("#side-foot", Static).update(Text(detail_foot(d) if d else ""))
        if moved:
            body.scroll_home(animate=False)
        self.refresh_bindings()

    def _side_changed(self, updated: set[str]) -> None:
        """Panels read again: what is remembered of them goes, and the pane reads its row again if its list is one."""
        self.side_cache = {at: d for at, d in self.side_cache.items() if at[0] not in updated}
        for name in updated:
            self.side_gen[name] = self.side_gen.get(name, 0) + 1
        if self._side_list() in updated:
            self._side_follow()

    def _side_acted(self) -> None:
        """An action ran: its entry has changed, whatever the next read says."""
        self.side_cache.clear()
        self.side_gen = {name: n + 1 for name, n in self.side_gen.items()} | {name: 1 for name in cockpit.COLUMNS
                                                                              if name not in self.side_gen}
        if self.beside:
            self._side_follow()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == self._side_list():
            self._side_follow()
            self.refresh_bindings()  # a, d, A wait for the row's own detail

    def action_side_back(self) -> None:
        self._focus_body()

    def action_side_open(self) -> None:
        self.open_links(self.side_d["links"])

    def action_side_act(self, kind: str) -> None:
        self.start_action(next(a for a in self.side_d["actions"] if a.kind == kind))

    def _side_allows(self, action: str, parameters: tuple) -> bool:
        """The pane's keys, shown and working when it shows the row under the cursor and that row has that link or
        action: until its detail is read, they wait, rather than act on the row the cursor left."""
        name, d = self._side_list(), self.side_d
        if name is None or not d or self.side_at != (name, self._side_row(name)):
            return False
        return bool(d["links"]) if action == "side_open" else any(a.kind == parameters[0] for a in d["actions"])
