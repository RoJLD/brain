"""The Milestones tab's Path view in the Textual cockpit (wi-brain-milestone-order; spec-brain-cockpit-ux2 §4.3.3,
UX-12): the ``path`` frame of the ``plan`` panel, an ``OptionList`` of brain.planpath's grid, read from the graph and
the forecast's latest.json by the cockpit's worker (brain.cockpit ``read_plan``, ``milestone_layers``).

From 120 columns (the screen's) the lanes: a row of the list is a row of the lanes, one milestone (or knot) a rank;
``←``/``→`` pick the milestone of the row (the picked one shown reversed), Enter opens its detail, a knot's its pairs
each way and how to settle it. Under 120 columns, the tree: a row a milestone, Enter its detail. A refresh keeps the
row and the picked rank.
"""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from . import cockpit, planpath, planviews


class PathView(OptionList):
    """The path frame: per project its heading (with several), the ranks' row, the lanes' rows (or the tree's), the
    tail; the picked rank (``col``) and the cursor's row kept across refreshes."""

    BINDINGS = [Binding("left", "cell(-1)", "Previous", show=False),
                Binding("right", "cell(1)", "Next", show=False)]

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.panel: dict | None = None
        self.col = 0
        self.rows: dict[str, dict] = {}   # option id: {project, cells [(node id, lines)] or node, col width, mode}
        self.paths: dict[str, dict] = {}    # project: its layers (``layers`` is a Textual widget's own)
        self._last: str | None = None       # the row the cursor was on: drawn plain again when it leaves

    def _width(self) -> int:
        return max(40, (self.scrollable_content_region.width or self.size.width or cockpit.NARROW_COLUMNS) - 1)

    def _columns(self) -> int:
        return self.app.size.width if self.is_mounted else cockpit.NARROW_COLUMNS

    def show(self, panel: dict | None) -> None:
        """The rows of ``panel`` at the frame's width, lanes from 120 screen columns; the cursor on the same row."""
        self.panel = panel
        key = _option_id(self)
        options, self.rows, self.paths = path_options(panel, self._width(), self._columns())
        self.clear_options()
        self.add_options(options)
        index = next((k for k, o in enumerate(options) if key and o.id == key), None)
        if index is None:
            index = next((k for k, o in enumerate(options) if not o.disabled), None)
        self.highlighted = index
        self._last = _option_id(self)
        self._mark()
        plain = planviews.words()
        self.border_subtitle = (f"{'<-/->' if plain else '←/→'} milestone · Enter detail · "
                                f"{planpath._sym(plain)['knot'][1].strip()} a mutual wait: brain milestone path --check")

    def _mark(self, old: str | None = None) -> None:
        """The picked cell of the cursor's row shown reversed; the row it left drawn plain again."""
        here = _option_id(self)
        for oid in {old, here} - {None}:
            r = self.rows.get(oid or "")
            if r and r["mode"] == "lanes":
                self.replace_option_prompt(oid, lane_text(r, self.col if oid == here else None))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        self._mark(self._last)
        self._last = event.option.id

    def action_cell(self, step: int) -> None:
        """←/→: the next milestone of the row, skipping the empty ranks."""
        r = self.rows.get(_option_id(self) or "")
        if not r or r["mode"] != "lanes":
            return
        filled = [k for k, (nid, _) in enumerate(r["cells"]) if nid]
        if not filled:
            return
        ahead = [k for k in filled if (k - self.col) * step > 0]
        if ahead:
            self.col = min(ahead, key=lambda k: abs(k - self.col))
        elif self.col not in filled:
            self.col = filled[0]
        self._mark()

    def picked(self) -> tuple[str, str] | None:
        """(project, node id) of the cursor's row: its picked cell (lanes), its node (tree)."""
        r = self.rows.get(_option_id(self) or "")
        if not r:
            return None
        if r["mode"] == "tree":
            return r["project"], r["node"]
        cells = r["cells"]
        k = self.col if self.col < len(cells) and cells[self.col][0] else next(
            (i for i, (nid, _) in enumerate(cells) if nid), None)
        return (r["project"], cells[k][0]) if k is not None else None

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter: the picked milestone's detail; a knot's pairs and how to settle it."""
        event.stop()
        hit = self.picked()
        if not hit:
            return
        project, nid = hit
        lay = self.paths.get(project) or {}
        node = next((n for n in lay.get("nodes") or [] if n["id"] == nid), None)
        if node is None:
            return
        if node["kind"] == "knot":
            knot = next(k for k in lay["knots"] if k["id"] == nid)
            from .tui_screens import ResultScreen
            self.app.push_screen(ResultScreen(f"{project}: a mutual wait", [
                {"exit": 0, "seconds": 0, "command": "brain milestone path --check",
                 "output": "\n".join(planpath.knot_lines(knot, project))}]))
            return
        row = next((m for m in lay.get("milestones") or [] if m["id"] == nid), {})
        self.app.open_detail("milestones", {"id": nid, "project": project, "done": row.get("done", 0),
                                            "items": row.get("items", 0), "title": row.get("title", "")})


def _option_id(view: OptionList) -> str | None:
    if view.highlighted is None or view.highlighted >= view.option_count:
        return None
    return view.get_option_at_index(view.highlighted).id


def lane_text(r: dict, col: int | None) -> Text:
    """A lanes row: its cells' lines side by side, the cell ``col`` reversed (None: none)."""
    text = Text()
    width = r["width"]
    lines = len(r["cells"][0][1]) if r["cells"] else 0
    for k in range(lines):
        if k:
            text.append("\n")
        for c, (nid, cell) in enumerate(r["cells"]):
            part = cell[k].ljust(width)
            text.append(part, style="reverse" if c == col and nid else "")
        text.rstrip()
    return text


def path_options(panel: dict | None, width: int, columns: int) -> tuple[list[Option], dict, dict]:
    """The frame's options: per project its heading (with several), the ranks' row, its rows (a lanes row, or a tree
    row), its tail; ({option id: row}, {project: layers})."""
    groups = (panel or {}).get("projects") or []
    options, rows, lays = [], {}, {}
    for g in groups:
        lay = g.get("path") or {}
        if len(groups) > 1 or "error" in g:
            text = f"error: {g['error']}" if "error" in g else planpath.heading(lay)
            options.append(Option(Text(f"{g['project']}: {text}"), disabled=True))
        if "error" not in g and lay:
            lays[g["project"]] = lay
            options += _project_options(g["project"], lay, width, columns, rows)
    if not groups:
        options.append(Option(Text("not read yet"), disabled=True))
    return options, rows, lays


def _project_options(project: str, lay: dict, width: int, columns: int, rows: dict) -> list[Option]:
    """One project's options (brain.planpath's grid), its rows added to ``rows``: a lanes row by its index, a tree row
    by its index and node."""
    grid = planpath.grid(lay, width, columns=columns)
    options = [Option(Text(h), disabled=True) for h in grid["head"]]
    for i, row in enumerate(grid["rows"]):
        if grid["mode"] == "lanes":
            oid = f"{project}:{i}"
            rows[oid] = {"mode": "lanes", "project": project, "cells": row, "width": grid["col"]}
            options.append(Option(lane_text(rows[oid], None), id=oid))
        else:
            oid = f"{project}:{i}:{row[0]}"
            rows[oid] = {"mode": "tree", "project": project, "node": row[0]}
            options.append(Option(Text(row[1]), id=oid))
    if not grid["rows"]:
        options.append(Option(Text("no arc between two milestones: no item of one waits on an item of another"),
                              disabled=True))
    return options + [Option(Text(t), disabled=True) for t in grid["tail"]]


class PathApp:
    """CockpitApp's part for the path frame."""

    def _draw_path(self, panel: dict | None) -> None:
        self._q("#path", PathView).show(panel)
