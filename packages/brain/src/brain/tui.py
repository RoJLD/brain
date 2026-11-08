"""The cockpit as a Textual app: ``brain tui`` with the ``tui`` extra (``pip install brain[tui]``; spec 2026-10-30
§3.6, Q7; spec 2026-11-02 cockpit-ux). brain.cockpit holds every read, row, filter and sort; this module only
lays the panels out and maps the keys.

The tabs (wi-brain-tui-layout, UX-18; brain.cockpit's ``TABS``): one per question, on a bar that says each one's state
(the queue's band now, the sessions asking, the open alerts). There is one widget per panel, in one grid: a tab or a view
is a layout of them, so a panel keeps its cursor and its scroll from one tab to another. Under 120 columns or 30 rows the
bar is reduced to its numbers and the grid is not offered (UX-2). The last tab and each tab's view are remembered.

Keys (the footer shows those of the focused panel, ? lists them all):
  0-9, ,   go to a tab: 0 overview, 1 queue, 2 sessions, 3 frontier, 4 milestones, 8 health (the number in a panel's
           title); 5 ideas, 6 lessons, 7 features, 9 resources and the comma (settings) wait for their items
  ctrl+pageup, ctrl+pagedown    the previous and the next tab (a click on the bar too, its tooltips name each tab)
  v        the tab's next view (the overview: its grid, its digest); a click on its word in the toolbar too
  p        the project selector: global (every registered project) or one project
  /        search every table (each word, case ignored); Enter keeps it, Escape clears it
  s, o     the focused panel's next sort, and its order reversed (sessions, queue, frontier); a column title too
  f        the focused panel's filters and sort, in a dialog
  i        what the focused panel shows, where it comes from and the command for the detail (a click on a
           panel's frame too: the [i] in its title, or the toolbar's)
  m        where a tab shows several panels, the focused one's full view, its breadcrumb in its title; Escape (or m)
           comes back
  Escape   back, one step at a time: the search cleared, a full view closed, then the overview
  space    pause the automatic refresh, and resume it (r still reads now)
  r        read everything again now, the probes too; + and - check the files more or less often (500 ms to 10 s)
  u        when the installed engine lags the brain's pin and the brain declares its installer (the title bar says
           « brain 0.2.1 · pin v0.2.3: -Apply »): the installer's plan, then -Apply on the owner's yes; else, when a
           newer engine is out (« 0.2.4 available »): brain update's plan, run on the owner's yes. Either way the
           cockpit closes and a window installs, then relaunches it (brain.handover)
  t        the times in this machine's timezone or in UTC
  Enter    the row's detail (brain.detail; a second click on a row too): a DDR's options, an item's spec, ADRs and
           PR, a session's plan...; in it, o opens a link (the file at its line in the editor, the PR in the
           browser, another item's detail), a answers a decision, d marks an action or a permission done, A applies
           an action's command: each after a confirmation that shows the exact brain command, run as the owner's and
           logged; Escape goes back
  q        quit
The states (brain.cockpit's ``why_empty``, ``probe_wait``): a table with no row says why in its one line (a filter or
the search hides N rows, and the key that changes it; nothing in the scope; a project not on this machine), a panel
not probed yet shows the probe's countdown, then its progress per project, and a project of the registry missing on
this machine is greyed in the selector (no registry: the tooltip says the selector holds this folder's project only).
The reads run in one worker thread at a time, so the screen never waits on them, and an error is shown as a
notification, never a crash: the panels of a read that fails keep their last content, the error and the time of the
data in their frame; an action's commands run in another, and the panels are read again after them. A refresh keeps
the view still: a table's cells are updated in place when its rows are the same, else it is rebuilt with its scroll where it was and its cursor on its record. The scope, the views and the
settings (the theme picked in the command palette, the timezone) are saved to <BRAIN_HOME>/tui.json at each change.
The title bar shows the installed version; once the screen is drawn, a worker reads whether a newer one is out
(brain.update.check: the engine's tags, cached 24 h, silent offline; the pin of config.json and the installer it
declares) and adds it there (« brain 0.2.2 · 0.2.3 available », « brain 0.2.1 · pin v0.2.3: -Apply »), so the first
paint never waits on it.
"""

from __future__ import annotations

import time
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, VerticalScroll
from textual.content import Content
from textual.markup import escape
from textual.widgets import DataTable, Footer, Header, Input, Label, Select, Static, Tab, Tabs

from . import cockpit, detail, handover, paths, update
from .tui_screens import AnswerScreen, ConfirmScreen, DetailScreen, PanelHelp, ResultScreen, ViewScreen

INTERVALS = (0.5, 1.0, 2.0, 5.0, 10.0)
TEXTS = {"audit": cockpit.audit_lines, "health": cockpit.health_lines, "exec": cockpit.exec_lines,
         "digest": lambda panel: cockpit.digest_lines(panel, width=1000, lines_max=0)}  # it scrolls: all of it
STYLES = {"sessions": {"asking": "bold magenta", "running": "green", "stale": "yellow", "idle": "cyan", "ended": "dim"},
          "alerts": {"critical": "bold red", "error": "red", "warn": "yellow", "info": "dim"}}  # the first column
MASTER_STYLES = {70: "yellow", 80: "bold dark_orange", 90: "bold red"}  # a master's row at each step (ST-4)
PANEL_ACTIONS = ("tab", "next_tab", "prev_tab", "next_view", "set_view", "back", "toggle_max", "pick_scope", "search",
                 "next_sort", "reverse", "filters", "panel_help", "toggle_tz",
                 "update")  # the panels' keys, off while a dialog or a detail is on top of them
EVERY_FRAME = (*cockpit.PANELS, *cockpit.FRAMES)
STATUS_COLUMNS = 100  # narrower, the global bar keeps its width for the search: the subtitle has the times


def _seconds(s: float) -> str:
    return f"{s * 1000:.0f} ms" if s < 1 else f"{s:g} s" if s < 60 else f"{s / 60:g} min"


class ViewTable(DataTable):
    """A table panel with a view (sessions, queue, frontier): its keys show in the footer while it has the focus."""
    BINDINGS = [Binding("s", "app.next_sort", "Sort"), Binding("o", "app.reverse", "Order"),
                Binding("f", "app.filters", "Filter")]


class SearchInput(Input):
    BINDINGS = [Binding("escape", "app.clear_search", "Clear")]


class CockpitApp(App):
    TITLE = update.title(None)  # the installed version; the newer one once the background check answers
    ESCAPE_TO_MINIMIZE = False  # Escape's steps are action_back's: the search before a full view
    CSS = """
    #bar { height: 1; }
    #bar Label { width: auto; padding: 0 1; color: $text-muted; }
    #scope { width: 34; }
    #search { width: 1fr; }
    #tabs { height: 1; }
    #tabs Underline { display: none; }
    #tabs Tab.-active { background: $primary; color: $text; text-style: bold; }
    #toolbar { height: 1; padding: 0 1; }
    #question { width: 1fr; color: $text-muted; }
    #views { width: auto; }
    #grid.all { grid-size: 2 5; grid-rows: 3fr 3fr 2fr 2fr 2fr; }
    #grid.all #sessions, #grid.all #digest { column-span: 2; }
    #grid.frames { grid-size: 3 2; grid-rows: 1fr 2fr; }
    #grid.frames #alerts { column-span: 3; }
    #grid.frames.stacked { grid-size: 1 4; grid-rows: 2fr 1fr 1fr 1fr; }
    #grid.frames.stacked #alerts { column-span: 1; }
    .panel { border: round $primary; height: 100%; }
    .panel:focus, .panel:focus-within { border: round $accent; }
    .panel.off { display: none; }
    """
    BINDINGS = [
        Binding("0", "tab('overview')", "Tabs", key_display="0-9"),  # the footer's word for the keys of every tab
        Binding("escape", "back", "Back"),
        Binding("i", "panel_help", "Info"),
        Binding("p", "pick_scope", "Project"),
        Binding("slash", "search", "Search", key_display="/"),
        Binding("v", "next_view", "View"),
        Binding("m", "toggle_max", "Full view"),
        Binding("r", "read_all", "Refresh"),
        Binding("space", "pause", "Pause"),
        Binding("question_mark", "keys", "Keys", key_display="?"),
        Binding("q", "quit", "Quit"),
        Binding("plus", "faster", "Faster", key_display="+", show=False),
        Binding("minus", "slower", "Slower", key_display="-", show=False),
        Binding("t", "toggle_tz", "Timezone", show=False),
        Binding("u", "update", "Update"),  # shown once a newer engine is out
        Binding("ctrl+pageup", "prev_tab", "Previous tab", show=False, priority=True),  # a table's own page left, right
        Binding("ctrl+pagedown", "next_tab", "Next tab", show=False, priority=True),
        *(Binding("comma" if t["key"] == "," else t["key"], f"tab('{name}')", cockpit.TABS[name]["label"]["en"],
                  show=False) for name, t in cockpit.TABS.items() if name != "overview"),
    ]

    def __init__(self, cp, refresh: float = cockpit.REFRESH_S, probe: float = cockpit.PROBE_S,
                 views: dict[str, dict] | None = None, search: str = "", settings: dict | None = None,
                 tab: str | None = None, tabs: dict[str, dict] | None = None) -> None:
        super().__init__()
        self.cockpit, self.refresh_s, self.probe_s = cp, refresh, probe
        self.views = {n: cockpit.view_of(n, (views or {}).get(n)) for n in cockpit.SORTS}
        self.search, self.scope = search, cp.scope
        self.settings = {"tz": "local", **(settings or {})}
        self.paused, self.checked_at = False, None
        self.pending: str | None = None  # a scope picked while a read runs: applied by the next one
        self.multi: bool | None = None  # whether the tables show the project column
        self.tab = tab if tab in cockpit.built_tabs() else "overview"
        self.tab_views = {t: v["view"] for t, v in (tabs or {}).items()}  # the view each tab last showed
        self.tab_focus: dict[str, str] = {}  # the panel each tab last focused
        self.framed = False  # the frame is mounted: a resize lays it out again
        self.last_panel = cockpit.tab_panels(self.tab)[0]
        self.busy = self.probing = False
        self.want_probe = True  # the first probe runs once the files are on screen
        self.next_probe = 0.0
        self.timer = None
        self.records: dict[str, dict[str, dict]] = {}  # each table's rows by key: the detail of the one selected
        self.notified: set[tuple] = set()  # the failed reads already notified: (at, error)
        self.update_info: dict | None = None  # brain.update.check's answer, once the background check has one
        self.handover: dict | None = None  # an install handed over (brain.handover.prepare): brain.tui.run starts it

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="bar"):
            yield Label("Project")
            yield Select(self._scopes(), value=self.scope, allow_blank=False, compact=True, id="scope",
                         tooltip="p: global, or one registered project" if getattr(self.cockpit, "registry", True)
                         else "p: no project registry (projects.yaml): this folder's project only")
            yield SearchInput(value=self.search, placeholder="/ search ids, titles, projects", compact=True,
                              id="search")
            yield Label(id="status")
        tabs = Tabs(*(Tab(Content(cockpit.tab_label(n, {})), id=f"tab-{n}") for n in cockpit.built_tabs()),
                    active=f"tab-{self.tab}", id="tabs")
        tabs.can_focus = False  # a click leaves the focus on the body, whose keys (s, o, f) go on working
        yield tabs
        with Horizontal(id="toolbar"):
            yield Label(id="question")
            yield Static(id="views")
        with Grid(id="grid"):  # one widget per panel: a tab or a view is a layout of them (_layout)
            for name in EVERY_FRAME:
                if name in cockpit.COLUMNS:
                    kind = ViewTable if name in cockpit.SORTS else DataTable
                    yield kind(id=name, classes="panel", zebra_stripes=True, cursor_type="row")
                else:
                    with VerticalScroll(id=name, classes="panel"):
                        yield Static(id=f"{name}-text")
        yield Footer()

    def _base(self):
        """The cockpit's own screen, even under the filter dialog or the help panel."""
        return self.screen_stack[0] if self.screen_stack else self.screen

    def _q(self, selector: str, kind=None):
        """A widget of the cockpit's own screen."""
        return self._base().query_one(selector, kind) if kind else self._base().query_one(selector)

    def _scopes(self) -> list[tuple]:
        """The selector's options; a project this machine lacks greyed (it can still be picked: its panels say so)."""
        return [(label if found else Text(label, style="dim"), value)
                for label, value, found in cockpit.scope_choices(self.cockpit.choices)]

    def on_mount(self) -> None:
        if self.settings.get("theme") in self.available_themes:
            self.theme = self.settings["theme"]
        self._columns()
        self.framed = True
        self._layout()
        self._subtitle()
        self.timer = self.set_interval(self.refresh_s, self.tick)
        self.watch(self.screen, "maximized", self._maximized, init=False)  # however the full view opens or closes
        self.tick(probe=False)
        self._focus_body()
        self.call_after_refresh(self._check_update)  # after the first paint, never before it (UPD-1)

    # --- the tabs: one widget per panel, a tab or a view is a layout of them (wi-brain-tui-layout) ---

    def _narrow(self) -> bool:
        return cockpit.narrow(self.size.width, self.size.height)

    def _view(self) -> str:
        """The view the tab shows: the one it last showed, when it is offered at this size."""
        return cockpit.tab_view(self.tab, self.tab_views.get(self.tab), self._narrow())

    def _layout(self) -> None:
        """The tab on screen: its view's panels shown and the others hidden, the grid arranged for them, its toolbar,
        the bar and the titles. The tables stay the same widgets, with their cursors and scrolls."""
        view, shown = self._view(), cockpit.tab_panels(self.tab, self._view())
        if getattr(self._base().maximized, "id", shown[0] if shown else None) not in shown:
            self._base().minimize()  # its panel left the screen: the grid gone on a narrow terminal
        self._q("#status").display = self.size.width >= STATUS_COLUMNS
        grid = self._q("#grid")
        grid.set_class(view == "grid", "all")
        grid.set_class(view == "frames", "frames")
        grid.set_class(self._narrow(), "stacked")
        for name in EVERY_FRAME:
            self._q(f"#{name}").set_class(name not in shown, "off")
        self._toolbar(view)
        self._bar()
        self._titles()
        self.refresh_bindings()

    def _toolbar(self, view: str) -> None:
        """The tab's question, its views (the one shown in brackets and bold; a click or v) and its [i]."""
        self._q("#question", Label).update(Content(cockpit.tab_question(self.tab)))
        lang, parts = cockpit.lang(), []
        views = cockpit.tab_views(self.tab, self._narrow())
        for v in views if len(views) > 1 else ():
            word = cockpit.VIEW_LABELS[v][lang]
            parts += [(f"[{word}]", "bold") if v == view else (word, f"underline @click=app.set_view('{v}')"), "  "]
        views_of = self._q("#views", Static)
        views_of.update(Content.assemble(*parts, ("[i]", "@click=app.panel_help")))
        views_of.tooltip = ("v: the tab's next view; " if len(views) > 1 else "") + "i: what this panel shows"

    def _bar(self) -> None:
        """The tab bar's words: each tab's name and count, its numbers alone when it is narrow or does not fit."""
        labels = cockpit.tab_labels(self.cockpit.snapshot(), self.tab, self.size.width, self.size.height)
        for name, label in labels.items():
            tab = self._q(f"#tab-{name}", Tab)
            if tab.label_text != label:
                tab.label = Content(label)
            tip = f"{cockpit.tab_title(name)} ({cockpit.TABS[name]['key']}): {cockpit.tab_question(name)}"
            if tab.tooltip != tip:  # its word and its key, whatever the bar shows of it
                tab.tooltip = tip

    def _focus_body(self) -> None:
        """The focus on the panel the tab last focused, else its first (once the layout has applied)."""
        shown = cockpit.tab_panels(self.tab, self._view())
        last = self.tab_focus.get(self.tab)
        self.last_panel = last if last in shown else shown[0]
        self.call_after_refresh(self._q(f"#{self.last_panel}").focus)

    def _show(self, name: str) -> None:
        self._base().minimize()
        self.tab = name
        self._save()
        self._layout()
        self._focus_body()

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """A click on the bar. A key has shown its tab already (action_tab), and an event of an earlier key is stale:
        the bar's active tab is the one that counts."""
        event.stop()
        name = event.tabs.active.removeprefix("tab-")
        if name != self.tab:
            self._show(name)

    def on_resize(self, event: events.Resize) -> None:
        if self.framed:
            self.call_after_refresh(self._resized)  # the app's own handler sets the size after this one

    def _resized(self) -> None:
        self._layout()
        if self.last_panel not in cockpit.tab_panels(self.tab, self._view()):  # the grid gone, on a narrow terminal
            self._focus_body()

    def action_tab(self, name: str) -> None:
        if not cockpit.TABS[name]["views"]:
            self.notify(cockpit.not_built(name), title=cockpit.tab_title(name), timeout=6)
        elif name == self.tab:  # its key again: the focus back on its body
            self._focus_body()
        else:
            self._q("#tabs", Tabs).active = f"tab-{name}"
            self._show(name)  # at once: the next key starts from this tab

    def _step_tab(self, step: int) -> None:
        built = cockpit.built_tabs()
        self.action_tab(built[(built.index(self.tab) + step) % len(built)])

    def action_next_tab(self) -> None:
        self._step_tab(+1)

    def action_prev_tab(self) -> None:
        self._step_tab(-1)

    def action_set_view(self, view: str) -> None:
        self._base().minimize()
        self.tab_views[self.tab] = view
        self._save()
        self._layout()
        self._focus_body()

    def action_next_view(self) -> None:
        views = cockpit.tab_views(self.tab, self._narrow())
        self.action_set_view(views[(views.index(self._view()) + 1) % len(views)])

    # --- the engine's version: a background check, then u ---

    def _check_update(self) -> None:
        self.run_worker(self._update_thread, thread=True, group="update", exit_on_error=False)

    def _update_thread(self) -> None:
        try:
            info = update.check(getattr(self.cockpit, "root", None))
        except Exception:  # silent: the title keeps the installed version
            return
        self.call_from_thread(self._updated, info)

    def _updated(self, info: dict) -> None:
        self.update_info = info
        self.title = update.title(info)
        self.refresh_bindings()
        if update.applies(info):
            self.notify(f"brain {info['installed']} lags the pin {info['pin']}: u shows the installer's plan "
                        f"({info['installer']} -Apply)", title="update", timeout=8)
        elif info.get("newer"):
            self.notify(f"brain {info['latest']} is out (this is {info['installed']}): u shows the update's plan",
                        title="update", timeout=8)

    # --- reading, in a worker thread ---

    def tick(self, probe: bool | None = None, force: bool = False) -> None:
        if self.busy:
            if self.probing:
                self._waits()  # the probe's progress, project by project
            return
        if self.paused and not force and self.pending is None:
            return
        scope, self.pending = self.pending, None
        if scope is not None:
            probe = False  # the files of the new scope first; its probe at the next tick when it never ran
        elif probe is None:
            probe = self.want_probe or time.monotonic() >= self.next_probe
        if probe:
            self.want_probe = False
            self.next_probe = time.monotonic() + self.probe_s
        self.busy, self.probing = True, probe
        self._subtitle()
        self.run_worker(lambda: self._read(probe, scope), thread=True, group="read", exit_on_error=False)

    def _read(self, probe: bool, scope: str | None = None) -> None:
        want = False
        try:
            if scope is not None:
                self.cockpit.select(scope)
                want = self.cockpit.needs_probe()
            updated, error = self.cockpit.refresh(probe=probe), ""
        except Exception as exc:  # shown, never fatal: the next tick tries again
            updated, error = set(), f"{type(exc).__name__}: {exc}"
        self.call_from_thread(self._done, updated, error, want)

    def _done(self, updated: set[str], error: str, want: bool = False) -> None:
        self.busy = self.probing = False
        self.checked_at = cockpit._iso(time.time())
        self.want_probe = self.want_probe or want
        if error:
            self.notify(error, title="brain tui", severity="error")
        failed: dict[tuple, list[str]] = {}
        for name, e in (self.cockpit.snapshot().get("errors") or {}).items():
            failed.setdefault((e["at"], e["error"]), []).append(name)
        for (at, text), names in failed.items():  # each failed read notified once; its panels keep their content
            if (at, text) not in self.notified:
                self.notified.add((at, text))
                self.notify(f"{text} ({', '.join(names)}: the last content kept)", title="brain tui",
                            severity="error")
        if self._columns():
            updated = set(cockpit.PANELS)
        self.draw(updated)
        self._waits()
        if self.pending is not None:
            self.tick()

    def _wait(self) -> str:
        """What a panel not probed yet waits for: the probe running, paused, or due in so many seconds."""
        progress = self.cockpit.snapshot().get("probing") or ({"what": "starting", "n": 0} if self.probing else None)
        due = None if self.want_probe else self.next_probe - time.monotonic()
        return cockpit.probe_wait(progress, due, self.paused)

    def _waits(self) -> None:
        """The probed panels not probed yet drawn again (their countdown, the probe's progress), and the subtitle."""
        panels = self.cockpit.snapshot()["panels"]
        waiting = {n for n in cockpit.PROBE_PANELS if panels.get(n) is None}
        if waiting:
            self.draw(waiting)
        self._subtitle()

    # --- drawing ---

    def _title(self, name: str, heading: str) -> str:
        """The key of the tab that opens the panel, its heading and its [i]; alone on the screen (its full view, a tab
        that is this panel), the scope before it (the breadcrumb)."""
        full = (getattr(self._base().maximized, "id", None) == name
                or cockpit.tab_panels(self.tab, self._view()) == (name,))
        crumb = f"{self.scope} > " if full else ""
        return escape(f"{crumb}{cockpit.TABS[cockpit.panel_tab(name)]['key']} {heading} [i]")

    def _maximized(self, widget) -> None:
        self._titles()
        self.refresh_bindings()

    def _titles(self) -> None:
        panels = self.cockpit.snapshot()["panels"]
        for name in EVERY_FRAME:
            panel = panels.get(cockpit.FRAMES.get(name, name))
            self._q(f"#{name}").border_title = self._title(name, cockpit.heading(name, panel))

    def _columns(self) -> bool:
        """The tables' columns for the scope (the project column only with several projects); True when changed."""
        multi = self.cockpit.multi
        if multi == self.multi:
            return False
        self.multi = multi
        for name in cockpit.COLUMNS:
            table = self._q(f"#{name}", DataTable)
            table.clear(columns=True)
            table.add_columns(*cockpit.columns(name, multi))
        return True

    def draw(self, updated: set[str]) -> None:
        snap = self.cockpit.snapshot()
        panels = snap["panels"]
        for name in EVERY_FRAME:
            source = cockpit.FRAMES.get(name, name)  # a frame is drawn when the panel it reads changes
            if source not in updated:
                continue
            panel = panels.get(source)
            widget = self._q(f"#{name}")
            widget.border_title = self._title(name, cockpit.heading(name, panel))
            if name in cockpit.COLUMNS:
                self._fill(widget, name, panel, snap)
                continue
            lines = TEXTS[name](panel)
            body = lines[1:] if name != "digest" else lines
            if panel is None:  # not probed yet, or its first probe failed
                error = (snap.get("errors") or {}).get(source)
                body = [f"read failed: {error['error']} (read again at the next probe)" if error else self._wait()]
            self._q(f"#{name}-text", Static).update(Text("\n".join(body)))
            widget.border_subtitle = escape(self._failed_note(source, snap))
        if updated:
            self._bar()

    def _failed_note(self, name: str, snap: dict) -> str:
        """A panel whose last read failed and that still shows its last content: the error and the data's time."""
        error = (snap.get("errors") or {}).get(name)
        if not error or snap["panels"].get(name) is None:
            return ""
        tz = self.settings["tz"]
        return (f"read failed {cockpit.when(error['at'], tz)}: {error['error']}; data of "
                f"{cockpit.when((snap.get('panel_at') or {}).get(name), tz)}")

    def _fill(self, table: DataTable, name: str, panel: dict | None, snap: dict | None = None) -> None:
        """The table's rows from the view, the view kept still. The same records in the same order: only the cells
        that changed are updated, the scroll and the cursor untouched. Otherwise the rows are rebuilt, the cursor
        on the record it was on (wherever the sort puts it, without scrolling to it), the scroll where it was."""
        view = self.views.get(name)
        rows: list[tuple[str, tuple]] = []
        seen: set[str] = set()
        self.records[name] = {}
        for r in cockpit.shown(name, panel, view, self.search):
            cells = cockpit.cells(name, r, self.multi is not False, self.settings["tz"])
            if name in STYLES:
                cells = (Text(cells[0], style=STYLES[name].get(cells[0], "")), *cells[1:])
            if name == "sessions" and r.get("ctx_step"):  # a master past 70, 80, 90 % of its budget
                cells = (cells[0], *(Text(str(c), style=MASTER_STYLES[r["ctx_step"]]) for c in cells[1:]))
            key = base = cockpit.row_key(name, r)
            while key in seen:
                key = f"{base}#{len(seen)}"
            seen.add(key)
            rows.append((key, cells))
            self.records[name][key] = r
        if not rows:
            rows.append(self._empty_row(name, panel, view, snap))
        keys = [k for k, _ in rows]
        if table.row_count and keys == [k.value for k in table.rows]:
            columns = [c.key for c in table.ordered_columns]
            for key, cells in rows:
                for column, new, old in zip(columns, cells, table.get_row(key)):
                    if new != old:  # the line that says why may grow: its column follows
                        table.update_cell(key, column, new, update_width=key == "~empty")
        else:
            keep, row = None, table.cursor_row
            if table.row_count:
                try:
                    keep = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                except Exception:  # the cursor out of the rows: keep its index
                    keep = None
            x, y = table.scroll_x, table.scroll_y
            table.clear()
            for key, cells in rows:
                table.add_row(*cells, key=key)
            if table.row_count:
                table.move_cursor(row=keys.index(keep) if keep in keys else min(row, table.row_count - 1),
                                  scroll=False)
            table.scroll_to(x, y, animate=False, immediate=True)
            self.call_after_refresh(table.scroll_to, x, y, animate=False)  # once the new rows have their size
        sub = cockpit.note(name, panel, view, self.search, sort=view is not None)
        if name == "queue" and (panel or {}).get("defaulted"):   # the defaults to review (brain decision defaulted)
            sub = f"{panel['defaulted']}; {sub}" if sub else panel["defaulted"]
        failed = self._failed_note(name, snap) if snap else ""
        table.border_subtitle = escape(f"{failed}; {sub}" if failed and sub else failed or sub)

    def _empty_row(self, name: str, panel: dict | None, view: dict | None, snap: dict | None) -> tuple[str, tuple]:
        """The one line of an empty table, which says why (no record behind it: Enter opens nothing)."""
        why = cockpit.why_empty(name, snap or {"panels": {name: panel}}, view, self.search, wait=self._wait())
        cols = cockpit.columns(name, self.multi is not False)
        return "~empty", tuple(Text(why, style="italic") if c == cockpit.EMPTY_COLUMN[name] else "" for c in cols)

    def _draw_tables(self) -> None:
        self.draw(set(cockpit.COLUMNS))

    def _subtitle(self) -> None:
        snap, tz = self.cockpit.snapshot(), self.settings["tz"]
        checked, changed = cockpit.when(self.checked_at, tz), cockpit.when(snap.get("read_at"), tz)
        probed = cockpit.when(snap.get("probed_at"), tz) if snap.get("probed_at") else "not yet"
        scope = (f"{snap['scope']} -> {self.pending}" if self.pending and self.pending != snap["scope"]
                 else snap["scope"])
        self.sub_title = (f"{scope} | files every {_seconds(self.refresh_s)}, checked {checked}, changed {changed} | "
                          f"probes every {_seconds(self.probe_s)}, run {probed} | {'UTC' if tz == 'utc' else 'local'}"
                          + (" | PAUSED (space resumes)" if self.paused else "")
                          + (f" | {self._wait()}" if self.probing else ""))
        due = None if self.want_probe else self.next_probe - time.monotonic()
        for status in self.screen_stack[0].query("#status") if self.screen_stack else ():  # none while the app closes
            status.update(Content(cockpit.bar_status(snap.get("read_at"), due, self.probing, self.paused, tz)))

    # --- the view: scope, search, sort, filters ---

    def _save(self) -> None:
        cockpit.save_state({"scope": self.scope, "panels": self.views, "settings": self.settings, "tab": self.tab,
                            "tabs": {t: {"view": v} for t, v in self.tab_views.items()}})

    def watch_theme(self, theme: str) -> None:
        """The theme picked in the command palette becomes the default one (saved with the settings)."""
        if self.is_mounted and theme != self.settings.get("theme"):
            self.settings["theme"] = theme
            self._save()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "scope" or event.value in (Select.BLANK, self.scope):
            return
        self.scope = self.pending = str(event.value)
        self._save()
        self._subtitle()
        self.tick()
        self._q(f"#{self.last_panel}").focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search" and event.value != self.search:
            self.search = event.value
            self._draw_tables()
            self.refresh_bindings()  # Escape's step

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self._q(f"#{self.last_panel}").focus()

    def on_descendant_focus(self, event) -> None:
        panel = next((w for w in event.widget.ancestors_with_self if w.has_class("panel")), None)
        if panel is not None:
            self.last_panel = self.tab_focus[self.tab] = panel.id

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        name = event.data_table.id
        key = cockpit.SORT_COLUMNS.get(name, {}).get(str(event.label))
        if key:
            v = self.views[name]
            self._set_view(name, {**v, "sort": key, "reverse": not v["reverse"] if v["sort"] == key else False})

    # --- the detail and its actions (brain.detail) ---

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        name = event.data_table.id
        r = self.records.get(name, {}).get(event.row_key.value)
        if r is not None:
            self.open_detail(name, r)

    def open_detail(self, name: str, r: dict) -> None:
        try:
            d = detail.of(name, r, self.cockpit)
        except Exception as exc:  # a detail that cannot be read is shown as an error, never a crash
            self.notify(f"{type(exc).__name__}: {exc}", title="detail", severity="error")
            return
        self.push_screen(DetailScreen(d))

    def open_link(self, x: dict) -> None:
        """A link of a detail: another item's detail, else the file in the editor or the PR in the browser."""
        if x["kind"] == "item":
            p = (getattr(self.cockpit, "choices", None) or {}).get(x.get("project"))
            self.push_screen(DetailScreen(detail.item(x["id"], p, detail._store(self.cockpit, p))))
            return
        _, terminal = detail.opener(x) if x["kind"] == "file" else (None, False)
        if terminal:  # a terminal editor ($EDITOR=vim): the screen is given back to it while it runs
            try:
                with self.suspend():
                    said = detail.open_link(x)
            except Exception as exc:  # suspending is not supported everywhere
                said = f"could not suspend the screen for $EDITOR: {exc}"
        else:
            said = detail.open_link(x)
        if said:
            self.notify(said, title="open")

    def start_action(self, a) -> None:
        """An action of a detail: its choice (an answer), then the confirmation of its exact commands, then its run."""
        why = detail.refused()
        if why:
            self.notify(why, title=a.label, severity="error")
            return
        if a.kind == "answer":
            title = next((s for s in self.screen_stack if isinstance(s, DetailScreen)), None)
            self.push_screen(AnswerScreen(a, title.d["title"] if title else a.ref),
                             lambda steps: self._confirm(a, steps) if steps else None)
        else:
            self._confirm(a, a.steps)

    def _confirm(self, a, steps: list[list[str]]) -> None:
        self.push_screen(ConfirmScreen(a, steps), lambda run: self._run_action(a, run) if run else None)

    def _run_action(self, a, steps: list[list[str]]) -> None:
        if a.handover:
            self._hand_over(a, steps)
            return
        self.notify(f"running: {detail.shown(steps[0])}", title=a.label)
        self.run_worker(lambda: self._action_thread(a, steps), thread=True, group="action", exit_on_error=False)

    def _action_thread(self, a, steps: list[list[str]]) -> None:
        try:
            results, error = detail.run(a, steps), ""
        except Exception as exc:  # refused, or the runner itself failed: shown, never fatal
            results, error = [], f"{type(exc).__name__}: {exc}"
        self.call_from_thread(self._action_done, a, steps, results, error)

    def _action_done(self, a, steps: list[list[str]], results: list[dict], error: str) -> None:
        ok = not error and len(results) == len(steps) and all(r["exit"] == 0 for r in results)
        self.notify(error or detail.summary(results), title=f"{a.label} {a.ref}",
                    severity="information" if ok else "error", timeout=12)
        if ok:
            while isinstance(self.screen, DetailScreen):  # the entry changed: back to the panels
                self.pop_screen()
        if results and (a.kind == "apply" or not ok):
            self.push_screen(ResultScreen(f"{a.label} {a.ref}", results))
        self.tick(force=True)  # the panels read again: the DDR answered, the stamp written

    def _hand_over(self, a, steps: list[list[str]]) -> None:
        """An engine install (INST-2): the cockpit holds the engine's files open (PyYAML's _yaml.pyd on Windows), so
        the steps run in a window once it has exited; it writes the handover, logged as the owner's action, and
        exits, and brain.tui.run starts the window, which relaunches brain tui with the same arguments."""
        try:
            self.handover = handover.prepare(a, steps)
        except Exception as exc:  # refused, or the script could not be written: shown, the cockpit stays
            self.notify(f"{type(exc).__name__}: {exc}", title=f"{a.label} {a.ref}", severity="error", timeout=12)
            return
        self.exit()

    def _set_view(self, name: str, view: dict | None) -> None:
        if view is None:
            return
        self.views[name] = cockpit.view_of(name, view)
        self._save()
        self.draw({name})

    def _view_panel(self) -> str | None:
        w = self.focused
        return w.id if isinstance(w, DataTable) and w.id in cockpit.SORTS else None

    def action_next_sort(self) -> None:
        name = self._view_panel()
        if name:
            v, keys = self.views[name], cockpit.SORTS[name]
            self._set_view(name, {**v, "sort": keys[(keys.index(v["sort"]) + 1) % len(keys)], "reverse": False})

    def action_reverse(self) -> None:
        name = self._view_panel()
        if name:
            self._set_view(name, {**self.views[name], "reverse": not self.views[name]["reverse"]})

    def action_filters(self) -> None:
        name = self._view_panel()
        if name:
            panel = self.cockpit.snapshot()["panels"].get(name)
            self.push_screen(ViewScreen(name, self.views[name], panel), lambda v: self._set_view(name, v))

    def action_pick_scope(self) -> None:
        select = self._q("#scope", Select)
        select.focus()
        select.expanded = True

    def action_search(self) -> None:
        self._q("#search", Input).focus()

    def action_clear_search(self) -> None:
        self._q("#search", Input).value = ""
        self._q(f"#{self.last_panel}").focus()

    # --- keys ---

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action in PANEL_ACTIONS and len(self.screen_stack) > 1:  # a dialog or a detail is open: its keys only
            return False
        if action == "back":  # nothing to go back from on the overview, no search, no full view
            return bool(self.search) or self.screen.maximized is not None or self.tab != "overview"
        if action == "next_view":  # shown on a tab with several views
            return len(cockpit.tab_views(self.tab, self._narrow())) > 1
        if action == "toggle_max":  # a tab of one panel is its full view already
            return len(cockpit.tab_panels(self.tab, self._view())) > 1
        if action == "update" and not ((self.update_info or {}).get("newer") or update.applies(self.update_info)):
            return False  # hidden until a newer one is out, or the installed one lags the pin
        return True

    def action_back(self) -> None:
        """Escape, one step at a time (spec cockpit-ux-round2 §4.0.5): the search, a full view, then the overview."""
        if self.search:
            self.action_clear_search()
        elif self.screen.maximized is not None:
            self.action_toggle_max()
        else:
            self.action_tab("overview")

    def action_panel_help(self, name: str | None = None) -> None:
        self.push_screen(PanelHelp(name or self.last_panel))

    def on_click(self, event: events.Click) -> None:
        """A click on a panel's frame, its top line (the [i] in its title): that panel's help."""
        panel = next((w for w in (event.widget.ancestors_with_self if event.widget else ()) if w.has_class("panel")),
                     None)
        if panel is not None and event.screen_y == panel.region.y:
            self.action_panel_help(panel.id)

    def action_update(self) -> None:
        """The engine the brain wants, on the owner's gesture, never the cockpit's own. When the installed engine
        lags the pin and the brain declares its installer (INST-1), the installer's plan (run without -Apply) in the
        confirmation, then -Apply on Run; else, when a newer tag is out (UPD-2), brain update's plan (brain update
        --check), then brain update --yes. Run hands over to a window that installs, then relaunches the cockpit."""
        info = self.update_info or {}
        then = ("Run closes the cockpit: a new window waits for it to exit, runs {cmd} there (its output stays in the "
                "window, a failure says so before anything else), then relaunches brain tui with the same arguments.")
        if update.applies(info):
            inst = info["installer"]
            self.start_action(detail.Action(
                kind="apply", label="Install", project="brain", ref=f"pin {info['pin']}", cwd=Path(info["root"]),
                steps=[[inst, "-Apply"]], preview=[inst], handover=True,
                plan=[f"brain {info['installed']} is installed and config.json engine.pin is {info['pin']}: the "
                      f"brain's installer ({inst}, config.json engine.installer) installs the pinned engine.",
                      then.format(cmd=f"{inst} -Apply")]))
        elif info.get("newer"):
            self.start_action(detail.Action(
                kind="apply", label="Update", project="brain", ref=f"v{info['latest']}", cwd=paths.brain_home(),
                steps=[["brain", "update", "--yes"]], preview=["brain", "update", "--check"], handover=True,
                plan=[f"Installs brain v{info['latest']} into the brain's venv and swaps its launcher; a pinned "
                      "brain's config.json engine.pin is then written, committed and brain sync run when the brain "
                      "declares no installer of its own (COMPAT-5), else left to move by a reviewed PR: the plan "
                      "below says which.",
                      then.format(cmd="brain update --yes")]))

    def action_pause(self) -> None:
        self.paused = not self.paused
        self._waits()

    def action_toggle_tz(self) -> None:
        self.settings["tz"] = "utc" if self.settings["tz"] == "local" else "local"
        self._save()
        self._subtitle()
        self.draw({"alerts"})

    def action_keys(self) -> None:
        if self.screen.query("HelpPanel"):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()

    def action_read_all(self) -> None:
        self.want_probe = True
        self.tick(force=True)

    def _interval(self, step: int) -> None:
        i = min(range(len(INTERVALS)), key=lambda k: abs(INTERVALS[k] - self.refresh_s))
        self.refresh_s = INTERVALS[max(0, min(len(INTERVALS) - 1, i + step))]
        if self.timer is not None:
            self.timer.stop()
        self.timer = self.set_interval(self.refresh_s, self.tick)
        self._subtitle()

    def action_faster(self) -> None:
        self._interval(-1)

    def action_slower(self) -> None:
        self._interval(+1)

    def action_toggle_max(self) -> None:
        if self.screen.maximized is not None:
            self.screen.minimize()
        else:
            self.screen.maximize(self._q(f"#{self.last_panel}"))


def run(cp, refresh: float = cockpit.REFRESH_S, probe: float = cockpit.PROBE_S, views: dict[str, dict] | None = None,
        search: str = "", settings: dict | None = None, tab: str | None = None,
        tabs: dict[str, dict] | None = None) -> int:
    app = CockpitApp(cp, refresh, probe, views, search, settings, tab, tabs)
    app.run()
    if app.handover:  # an install handed over: the window starts once the app is gone (brain.handover)
        return handover.start(app.handover)
    return 0
