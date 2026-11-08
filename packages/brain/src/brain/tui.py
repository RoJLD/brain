"""The cockpit as a Textual app: ``brain tui`` with the ``tui`` extra (``pip install brain[tui]``; spec 2026-10-30
§3.6, Q7; spec 2026-11-02 cockpit-ux). brain.cockpit holds every read, row, filter and sort; this module only
lays the panels out and maps the keys.

Keys (the footer shows those of the focused panel, ? lists them all):
  p        the project selector: global (every registered project) or one project
  /        search every table (each word, case ignored); Enter keeps it, Escape clears it
  1-8      go to a panel (the number in its title); in the full view, that panel's full view
  s, o     the focused panel's next sort, and its order reversed (sessions, queue, frontier); a column title too
  f        the focused panel's filters and sort, in a dialog
  i        what the focused panel shows, where it comes from and the command for the detail (a click on a
           panel's frame too: the [i] in its title)
  m        the focused panel's full view, its breadcrumb in its title; Escape (or m) comes back
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
from dataclasses import replace
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.screen import ModalScreen
from textual.widgets import (Button, Checkbox, DataTable, Footer, Header, Input, Label, OptionList, RadioButton,
                             RadioSet, Select, Static)

from . import cockpit, config, detail, handover, paths, update

INTERVALS = (0.5, 1.0, 2.0, 5.0, 10.0)
TEXTS = {"audit": cockpit.audit_lines, "health": cockpit.health_lines,
         "digest": lambda panel: cockpit.digest_lines(panel, width=1000, lines_max=0)}  # it scrolls: all of it
STYLES = {"sessions": {"asking": "bold magenta", "running": "green", "stale": "yellow", "idle": "cyan", "ended": "dim"},
          "alerts": {"critical": "bold red", "error": "red", "warn": "yellow", "info": "dim"}}  # the first column
MASTER_STYLES = {70: "yellow", 80: "bold dark_orange", 90: "bold red"}  # a master's row at each step (ST-4)
PANEL_ACTIONS = ("go", "toggle_max", "pick_scope", "search", "next_sort", "reverse", "filters", "panel_help",
                 "toggle_tz", "update")  # the panels' keys, off while a dialog or a detail is on top of them


def _seconds(s: float) -> str:
    return f"{s * 1000:.0f} ms" if s < 1 else f"{s:g} s" if s < 60 else f"{s / 60:g} min"


class ViewTable(DataTable):
    """A table panel with a view (sessions, queue, frontier): its keys show in the footer while it has the focus."""
    BINDINGS = [Binding("s", "app.next_sort", "Sort"), Binding("o", "app.reverse", "Order"),
                Binding("f", "app.filters", "Filter")]


class SearchInput(Input):
    BINDINGS = [Binding("escape", "app.clear_search", "Clear")]


class ViewScreen(ModalScreen):
    """One panel's filters and sort: Apply keeps them, Reset brings the defaults back, Escape changes nothing."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CSS = """
    ViewScreen { align: center middle; }
    #dialog { width: 64; height: auto; border: round $accent; padding: 1 2; background: $surface; }
    #dialog .field { margin-top: 1; color: $text-muted; }
    #buttons { height: auto; margin-top: 1; }
    #buttons Button { margin-right: 1; }
    """

    def __init__(self, name: str, view: dict | None, panel: dict | None) -> None:
        super().__init__()
        self.panel_name, self.view, self.panel = name, cockpit.view_of(name, view), panel

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"{cockpit.title(self.panel_name)}: filters and sort")
            for field in cockpit.FILTERS[self.panel_name]:
                values = cockpit.choices(self.panel_name, field, self.panel)
                if self.view[field] not in values:
                    values = (*values, self.view[field])
                yield Label(field.capitalize(), classes="field")
                yield Select([(v, v) for v in values], value=self.view[field], allow_blank=False, id=f"f-{field}")
            yield Label("Sort", classes="field")
            yield Select([(k, k) for k in cockpit.SORTS[self.panel_name]], value=self.view["sort"],
                         allow_blank=False, id="sort")
            yield Checkbox("Reversed order", self.view["reverse"], id="reverse")
            with Horizontal(id="buttons"):
                yield Button("Apply", variant="primary", id="apply")
                yield Button("Reset", id="reset")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply":
            view = {f: self.query_one(f"#f-{f}", Select).value for f in cockpit.FILTERS[self.panel_name]}
            self.dismiss({**view, "sort": self.query_one("#sort", Select).value,
                          "reverse": self.query_one("#reverse", Checkbox).value})
        elif event.button.id == "reset":
            self.dismiss(cockpit.view_of(self.panel_name))
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PanelHelp(ModalScreen):
    """A panel's help (cockpit.HELP): Escape, Enter or i closes it."""
    BINDINGS = [Binding("escape,enter,i", "close", "Close")]
    CSS = """
    PanelHelp { align: center middle; }
    #help { width: 90; max-width: 95%; height: auto; border: round $accent; padding: 1 2; background: $surface; }
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self.panel_name = name

    def compose(self) -> ComposeResult:
        with Vertical(id="help"):
            yield Label(f"[b]{escape(cockpit.heading(self.panel_name, None).split(' (')[0].split(':')[0])}[/b]")
            yield Static(Text("\n".join(cockpit.help_lines(self.panel_name))))

    def action_close(self) -> None:
        self.dismiss(None)


class DetailScreen(ModalScreen):
    """A row's detail (brain.detail): o opens a link, a, d and A run its actions after a confirmation; Escape goes
    back."""
    BINDINGS = [Binding("escape", "close", "Back"), Binding("o", "open", "Open"),
                Binding("a", "act('answer')", "Answer"), Binding("d", "act('done')", "Done"),
                Binding("A", "act('apply')", "Apply", key_display="A")]
    CSS = """
    DetailScreen { align: center middle; }
    #detail { width: 96%; height: 92%; border: round $accent; background: $surface; padding: 0 1; }
    #detail-title { text-style: bold; width: 1fr; margin-bottom: 1; }
    #detail-body { height: 1fr; }
    #detail-body .heading { margin-top: 1; }
    #detail-body .heading.first { margin-top: 0; }
    #detail-body .line { padding-left: 2; }
    #detail-foot { height: auto; color: $text-muted; margin-top: 1; }
    """

    def __init__(self, d: dict) -> None:
        super().__init__()
        self.d = d
        self.acts = {a.kind: a for a in d["actions"]}

    def compose(self) -> ComposeResult:
        with Vertical(id="detail"):
            yield Label(Text(self.d["title"]), id="detail-title")
            with VerticalScroll(id="detail-body"):
                for i, (heading, lines) in enumerate(self.d["sections"]):
                    yield Static(Text(heading, style="bold"), classes="heading" + (" first" if not i else ""))
                    for line in lines:  # one widget a line: a wrapped line keeps its indent
                        yield Static(Text(line), classes="line")
            yield Static(Text(_foot(self.d)), id="detail-foot")
        yield Footer()

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "open":
            return bool(self.d["links"])
        if action == "act":
            return parameters[0] in self.acts
        return True

    def action_close(self) -> None:
        self.dismiss(None)

    def action_open(self) -> None:
        links = self.d["links"]
        if len(links) == 1:
            self.app.open_link(links[0])
        else:
            self.app.push_screen(LinkScreen(links), lambda i: self.app.open_link(links[i]) if i is not None else None)

    def action_act(self, kind: str) -> None:
        self.app.start_action(self.acts[kind])


def _foot(d: dict) -> str:
    keys = {"answer": "a", "done": "d", "apply": "A"}
    acts = "; ".join(f"{keys[a.kind]} {a.label}: " + ("; then ".join(detail.shown(s) for s in a.steps) if a.steps
                                                       else "brain decision answer ... --via tui --by "
                                                       + config.owner_of())  # the id --by writes
                     for a in d["actions"])
    parts = [f"o opens: {', '.join(x['label'] for x in d['links'][:4])}"
             + (f" (+{len(d['links']) - 4})" if len(d["links"]) > 4 else "")] if d["links"] else []
    if acts:
        parts.append(("Actions, refused here: " + d["refused"] + ". " if d.get("refused") else "Actions: ") + acts)
    return "\n".join(parts)


class LinkScreen(ModalScreen):
    """The links of a detail: Enter opens the one picked, Escape none."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CSS = """
    LinkScreen { align: center middle; }
    #links { width: 90%; max-height: 80%; border: round $accent; background: $surface; }
    """

    def __init__(self, links: list[dict]) -> None:
        super().__init__()
        self.links = links

    def compose(self) -> ComposeResult:
        yield OptionList(*(Text(detail.link_text(x)) for x in self.links), id="links")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_index)

    def action_cancel(self) -> None:
        self.dismiss(None)


class AnswerScreen(ModalScreen):
    """Answer a decision: one option (or several when it is multiple choice), an other answer, notes; Answer goes
    to the confirmation, Escape changes nothing."""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CSS = """
    AnswerScreen { align: center middle; }
    #answer { width: 90%; height: auto; max-height: 92%; border: round $accent; padding: 1 2; background: $surface; }
    #answer .field { margin-top: 1; color: $text-muted; }
    #answer Input { margin-top: 1; }
    #answer-buttons { height: auto; margin-top: 1; }
    #answer-buttons Button { margin-right: 1; }
    """

    def __init__(self, a, title: str) -> None:
        super().__init__()
        self.a, self.title_text = a, title

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="answer"):
            yield Label(Text(self.title_text, style="bold"))
            yield Label("Pick one or more options" if self.a.multi else "Pick one option", classes="field")
            labels = [Text(f"{o['label']}" + (f": {' '.join(o['consequences'].split())}" if o.get("consequences")
                                              else "")) for o in self.a.options]
            if self.a.multi:
                for i, label in enumerate(labels):
                    yield Checkbox(label, id=f"opt-{i}")
            else:
                yield RadioSet(*(RadioButton(label) for label in labels), id="options")
            yield Input(placeholder=f"Other: {config.name_of()}'s own answer, free text", id="other")
            yield Input(placeholder="Notes (optional)", id="notes")
            with Horizontal(id="answer-buttons"):
                yield Button("Answer", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    def picked(self) -> list[str]:
        labels = [o["label"] for o in self.a.options]
        if self.a.multi:
            return [lab for i, lab in enumerate(labels) if self.query_one(f"#opt-{i}", Checkbox).value]
        i = self.query_one("#options", RadioSet).pressed_index
        return [labels[i]] if i >= 0 else []

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "ok":
            self.dismiss(None)
            return
        try:
            steps = detail.answer_steps(self.a, self.picked(), self.query_one("#other", Input).value,
                                        self.query_one("#notes", Input).value)
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self.dismiss(steps)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen):
    """The exact commands an action runs, in their folder, before they run: Run (y) or Cancel (n, Escape). An action
    marked done takes an optional note."""
    BINDINGS = [Binding("escape,n", "cancel", "Cancel"), Binding("y", "run", "Run")]
    CSS = """
    ConfirmScreen { align: center middle; }
    #confirm { width: 90%; height: auto; max-height: 92%; border: thick $warning; padding: 1 2; background: $surface; }
    #confirm .field { margin-top: 1; color: $text-muted; }
    #confirm-buttons { height: auto; margin-top: 1; }
    #confirm-buttons Button { margin-right: 1; }
    """

    def __init__(self, a, steps: list[list[str]]) -> None:
        super().__init__()
        self.a, self.steps = a, steps

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="confirm"):
            yield Label(Text(f"{self.a.label} {self.a.ref}: run as {config.name_of()}, logged as their action?",
                             style="bold"))
            yield Label(Text(f"in {self.a.cwd}"), classes="field")
            yield Static(Text("\n".join(f"$ {detail.shown(s)}" for s in self.steps)), id="commands")
            yield Static(Text("\n".join(self.a.plan)), classes="field")
            if self.a.preview:
                yield Static(Text(f"The plan: running {detail.shown(self.a.preview)}..."), id="plan")
            if self.a.note:
                yield Input(placeholder="Note: what was done (granted by an allow rule, done once...), optional",
                            id="note")
            with Horizontal(id="confirm-buttons"):
                yield Button("Run (y)", variant="warning", id="run")
                yield Button("Cancel (n)", id="cancel")

    def on_mount(self) -> None:
        run = self.query_one("#run", Button)
        run.focus()
        if self.a.preview:  # an apply's plan first (install.ps1 without -Apply): Run waits for it
            run.disabled = True
            self.run_worker(self._plan, thread=True, exit_on_error=False)

    def _plan(self) -> None:
        plan = replace(self.a, kind="plan", label="Plan", steps=[self.a.preview], preview=None)
        try:
            res = detail.run(plan, plan.steps)
        except Exception as exc:  # refused, or the runner failed: shown in the dialog
            res = [{"command": detail.shown(self.a.preview), "exit": None, "seconds": 0,
                    "output": f"{type(exc).__name__}: {exc}"}]
        self.app.call_from_thread(self._planned, res)

    def _planned(self, res: list[dict]) -> None:
        r = res[0]
        head = f"The plan ({r['command']}): " + ("" if r["exit"] == 0 else f"failed, exit {r['exit']}; ")
        self.query_one("#plan", Static).update(Text(head + "\n" + (r["output"] or "(no output)"),
                                                     style="" if r["exit"] == 0 else "red"))
        run = self.query_one("#run", Button)
        run.disabled = False
        run.focus()

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "run":  # y waits for the plan as the button does
            return not self.query_one("#run", Button).disabled
        return True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run":
            self.action_run()
        else:
            self.dismiss(None)

    def action_run(self) -> None:
        note = self.query_one("#note", Input).value if self.a.note else ""
        self.dismiss(detail.done_steps(self.a, note) if self.a.kind == "done" else self.steps)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ResultScreen(ModalScreen):
    """What an action's commands printed: Escape or Enter closes it."""
    BINDINGS = [Binding("escape,enter", "close", "Close")]
    CSS = """
    ResultScreen { align: center middle; }
    #result { width: 90%; height: auto; max-height: 90%; border: round $accent; padding: 1 2; background: $surface; }
    """

    def __init__(self, title: str, results: list[dict]) -> None:
        super().__init__()
        self.title_text, self.results = title, results

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="result"):
            yield Label(Text(self.title_text, style="bold"))
            for r in self.results:
                ok = r["exit"] == 0
                yield Label(Text(f"{'ok' if ok else 'failed, exit ' + str(r['exit'])} in {r['seconds']} s: "
                                 f"{r['command']}", style="green" if ok else "bold red"))
                yield Static(Text(r["output"] or "(no output)"))

    def action_close(self) -> None:
        self.dismiss(None)


class CockpitApp(App):
    TITLE = update.title(None)  # the installed version; the newer one once the background check answers
    CSS = """
    #bar { height: 1; }
    #bar Label { width: auto; padding: 0 1; color: $text-muted; }
    #scope { width: 34; }
    #search { width: 1fr; }
    #grid { grid-size: 2 5; grid-rows: 3fr 3fr 2fr 2fr 2fr; }
    #sessions, #digest { column-span: 2; }
    .panel { border: round $primary; height: 100%; }
    .panel:focus, .panel:focus-within { border: round $accent; }
    """
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("i", "panel_help", "Info"),
        Binding("p", "pick_scope", "Project"),
        Binding("slash", "search", "Search", key_display="/"),
        Binding("m", "toggle_max", "Full view"),
        Binding("r", "read_all", "Refresh"),
        Binding("space", "pause", "Pause"),
        Binding("question_mark", "keys", "Keys", key_display="?"),
        Binding("q", "quit", "Quit"),
        Binding("plus", "faster", "Faster", key_display="+", show=False),
        Binding("minus", "slower", "Slower", key_display="-", show=False),
        Binding("t", "toggle_tz", "Timezone", show=False),
        Binding("u", "update", "Update"),  # shown once a newer engine is out
        *(Binding(str(i), f"go({i})", f"Panel {i}", show=False) for i in range(1, len(cockpit.PANELS) + 1)),
    ]

    def __init__(self, cp, refresh: float = cockpit.REFRESH_S, probe: float = cockpit.PROBE_S,
                 views: dict[str, dict] | None = None, search: str = "", settings: dict | None = None) -> None:
        super().__init__()
        self.cockpit, self.refresh_s, self.probe_s = cp, refresh, probe
        self.views = {n: cockpit.view_of(n, (views or {}).get(n)) for n in cockpit.SORTS}
        self.search, self.scope = search, cp.scope
        self.settings = {"tz": "local", **(settings or {})}
        self.paused, self.checked_at = False, None
        self.pending: str | None = None  # a scope picked while a read runs: applied by the next one
        self.multi: bool | None = None  # whether the tables show the project column
        self.last_panel = cockpit.PANELS[0]
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
        with Grid(id="grid"):
            for name in cockpit.PANELS:
                if name in cockpit.COLUMNS:
                    kind = ViewTable if name in cockpit.SORTS else DataTable
                    yield kind(id=name, classes="panel", zebra_stripes=True, cursor_type="row")
                else:
                    with VerticalScroll(id=name, classes="panel"):
                        yield Static(id=f"{name}-text")
        yield Footer()

    def _q(self, selector: str, kind=None):
        """A widget of the cockpit's own screen, even under the filter dialog or the help panel."""
        screen = self.screen_stack[0] if self.screen_stack else self.screen
        return screen.query_one(selector, kind) if kind else screen.query_one(selector)

    def _scopes(self) -> list[tuple]:
        """The selector's options; a project this machine lacks greyed (it can still be picked: its panels say so)."""
        return [(label if found else Text(label, style="dim"), value)
                for label, value, found in cockpit.scope_choices(self.cockpit.choices)]

    def on_mount(self) -> None:
        if self.settings.get("theme") in self.available_themes:
            self.theme = self.settings["theme"]
        self._columns()
        for name in cockpit.PANELS:
            self._q(f"#{name}").border_title = self._title(name, cockpit.heading(name, None))
        self._subtitle()
        self.timer = self.set_interval(self.refresh_s, self.tick)
        self.watch(self.screen, "maximized", self._maximized, init=False)  # however the full view opens or closes
        self.tick(probe=False)
        self._q(f"#{self.last_panel}").focus()
        self.call_after_refresh(self._check_update)  # after the first paint, never before it (UPD-1)

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
        """The panel's number, its heading and its [i]; in its full view, the scope before it (the breadcrumb)."""
        full = self.screen.maximized is not None and getattr(self.screen.maximized, "id", None) == name
        crumb = f"{self.scope} > " if full else ""
        return escape(f"{crumb}{cockpit.PANELS.index(name) + 1} {heading} [i]")

    def _maximized(self, widget) -> None:
        self._titles()
        self.refresh_bindings()

    def _titles(self) -> None:
        panels = self.cockpit.snapshot()["panels"]
        for name in cockpit.PANELS:
            self._q(f"#{name}").border_title = self._title(name, cockpit.heading(name, panels.get(name)))

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
        for name in cockpit.PANELS:
            if name not in updated:
                continue
            panel = panels.get(name)
            widget = self._q(f"#{name}")
            widget.border_title = self._title(name, cockpit.heading(name, panel))
            if name in cockpit.COLUMNS:
                self._fill(widget, name, panel, snap)
                continue
            lines = TEXTS[name](panel)
            body = lines[1:] if name != "digest" else lines
            if panel is None:  # not probed yet, or its first probe failed
                error = (snap.get("errors") or {}).get(name)
                body = [f"read failed: {error['error']} (read again at the next probe)" if error else self._wait()]
            self._q(f"#{name}-text", Static).update(Text("\n".join(body)))
            widget.border_subtitle = escape(self._failed_note(name, snap))

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

    # --- the view: scope, search, sort, filters ---

    def _save(self) -> None:
        cockpit.save_state({"scope": self.scope, "panels": self.views, "settings": self.settings})

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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self._q(f"#{self.last_panel}").focus()

    def on_descendant_focus(self, event) -> None:
        panel = next((w for w in event.widget.ancestors_with_self if w.has_class("panel")), None)
        if panel is not None:
            self.last_panel = panel.id

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

    def action_go(self, i: int) -> None:
        widget = self._q(f"#{cockpit.PANELS[i - 1]}")
        if self.screen.maximized is not None:
            self.screen.minimize()
            self.screen.maximize(widget)
        widget.focus()

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "back":  # shown in the footer in a full view only
            return self.screen.maximized is not None
        if action == "update" and not ((self.update_info or {}).get("newer") or update.applies(self.update_info)):
            return False  # hidden until a newer one is out, or the installed one lags the pin
        if action in PANEL_ACTIONS and len(self.screen_stack) > 1:  # a dialog or a detail is open: its keys only
            return False
        return True

    def action_back(self) -> None:
        if self.screen.maximized is not None:
            self.action_toggle_max()

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
        search: str = "", settings: dict | None = None) -> int:
    app = CockpitApp(cp, refresh, probe, views, search, settings)
    app.run()
    if app.handover:  # an install handed over: the window starts once the app is gone (brain.handover)
        return handover.start(app.handover)
    return 0
