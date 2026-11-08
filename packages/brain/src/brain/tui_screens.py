"""The cockpit's dialogs (``brain tui``, the ``tui`` extra): a panel's filters and sort, its help, a row's detail and its
links, the answer to a decision, the confirmation of a command and what it printed. Each is a modal screen on top of the
panels; the app (``brain.tui``) opens them, runs what they return, and holds the panels' keys off while one is open.
"""

from __future__ import annotations

from dataclasses import replace

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.screen import ModalScreen
from textual.widgets import (Button, Checkbox, Footer, Input, Label, OptionList, RadioButton, RadioSet, Select, Static)

from . import cockpit, config, detail


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
