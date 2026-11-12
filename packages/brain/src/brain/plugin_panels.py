"""A plugged project's cockpit panels and tabs, declared as data (wi-brain-command-plugins-cockpit; spec cockpit-ux
§4.11, cockpit-ux-round2 §4.0.1 and §5). The second slice of the command plugins (brain.plugins): the first plugs a
project's subcommands, this one its panels.

A project's plugin (its ``plugin`` key in projects.yaml) declares them in a ``COCKPIT`` mapping, an attribute of the
object the plugin names or of its module (a callable returning the mapping works too). Nothing of it is Textual code:
the cockpit draws each panel as one of its own tables, so the project selector, the search, the sorts, the filters,
the saved views, the column chooser and the text view work on it as on the built-in panels::

    COCKPIT = {
        "v": 1,
        "panels": {
            "runs": {
                "title": "Runs",                         # or {"en": "Runs", "fr": "Exécutions"}
                "rows": "out/runs.json",                 # a JSON file under the project's root: a list of objects,
                                                         # or {"rows": [...]}
                # "read": "orbit.cockpit:runs",          # or a callable (module:attr), given the project's root
                "columns": [{"key": "id", "title": "Id"}, {"key": "state", "title": "State"}],
                "sorts": ["state", "id"],                # column keys; the first is the default
                "filters": {"state": ["all", "ok", "failed"]},   # "all" first: no filter
                "id": "id",                              # the field that names a row (default id)
                "help": "The last runs of the backtests.",
            },
        },
        "tabs": [{"id": "runs", "label": {"en": "Runs"}, "panels": ["runs"]}],   # default: one tab, the project's
    }

Each panel becomes ``<project>-<panel>`` in the cockpit's tables (brain.cockpit's ``plug``), and each tab
``<project>`` (or ``<project>-<tab>``), placed after Resources with no number: a click, the palette or ctrl+pagedown
reach it. A key or a value this engine does not know is kept and noted (``notes``), never an error; a plugin that
cannot be loaded, or a declaration it cannot read, is noted and leaves the other panels as they are. The rows are read
once when the panel shows and at each probe (r reads them again), in the reading thread: zero token.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

V = 1
PANEL_KEYS = {"title", "rows", "read", "columns", "sorts", "filters", "id", "help"}
TAB_KEYS = {"id", "label", "question", "panels"}
TOP_KEYS = {"v", "panels", "tabs"}
ALL = "all"
_ID_RE = re.compile(r"[^a-z0-9-]+")


@dataclass
class Panel:
    name: str                 # <project>-<panel>: its name in the cockpit's tables
    project: str
    own: str                  # the plugin's own name for it
    title: dict               # {lang: title}
    columns: tuple            # ((key, title), ...)
    sorts: tuple              # column keys, the default first
    filters: dict             # {field: (values...)}, ALL first
    id_field: str = "id"
    rows_file: str = ""
    read: str = ""
    help: str = ""
    ref: str = ""             # the plugin as declared


@dataclass
class Tab:
    name: str
    project: str
    label: dict
    question: dict
    panels: tuple


@dataclass
class Plugged:
    panels: dict = field(default_factory=dict)   # name -> Panel
    tabs: dict = field(default_factory=dict)     # name -> Tab
    notes: list = field(default_factory=list)    # what was left out or tolerated, and why


def slug(text: str) -> str:
    return _ID_RE.sub("-", str(text).lower()).strip("-") or "x"


def _texts(value, default: str) -> dict:
    """A title or a label as {en, fr}: a string for both, a mapping per language (the English one for a missing one)."""
    if isinstance(value, dict):
        en = str(value.get("en") or value.get("fr") or default)
        return {"en": en, "fr": str(value.get("fr") or en)}
    return {"en": str(value or default), "fr": str(value or default)}


def declaration(obj):
    """The ``COCKPIT`` mapping of a loaded plugin: the object's attribute, else its module's; called when callable;
    None when it declares none."""
    decl = getattr(obj, "COCKPIT", None)
    if decl is None:
        decl = getattr(sys.modules.get(getattr(obj, "__module__", "") or ""), "COCKPIT", None)
    return decl() if callable(decl) else decl


def parse(project: str, ref: str, decl, notes: list) -> tuple[dict, dict]:
    """A declaration's panels and tabs ({name: Panel}, {name: Tab}); what it cannot use is noted and left out."""
    if not isinstance(decl, dict):
        notes.append(f"{project}: COCKPIT is a mapping (v, panels, tabs), got {type(decl).__name__}: left out")
        return {}, {}
    if decl.get("v", V) != V:
        notes.append(f"{project}: COCKPIT v {decl.get('v')!r}, this engine reads v {V}: read as v {V}")
    for k in sorted(set(decl) - TOP_KEYS):
        notes.append(f"{project}: COCKPIT key {k!r} unknown to this engine: kept, not used")
    panels = {}
    for own, spec in (decl.get("panels") or {}).items() if isinstance(decl.get("panels"), dict) else ():
        p = _panel(project, ref, str(own), spec, notes)
        if p is not None:
            panels[p.name] = p
    tabs = {}
    given = decl.get("tabs")
    for spec in given if isinstance(given, list) else []:
        t = _tab(project, spec, panels, notes)
        if t is not None:
            tabs[t.name] = t
    if panels and not tabs:  # one tab, named by the project, with every panel
        name = slug(project)
        tabs[name] = Tab(name, project, _texts(None, project), _texts(None, f"What {project}'s plugin shows"),
                         tuple(panels))
    return panels, tabs


def _panel(project: str, ref: str, own: str, spec, notes: list) -> Panel | None:
    where = f"{project}: panel {own!r}"
    if not isinstance(spec, dict):
        notes.append(f"{where}: a mapping, got {type(spec).__name__}: left out")
        return None
    for k in sorted(set(spec) - PANEL_KEYS):
        notes.append(f"{where}: key {k!r} unknown to this engine: kept, not used")
    rows, read = spec.get("rows"), spec.get("read")
    if not (isinstance(rows, str) and rows) and not (isinstance(read, str) and ":" in read):
        notes.append(f"{where}: neither rows (a JSON file) nor read (module:attr): left out")
        return None
    cols = []
    for c in spec.get("columns") or []:
        if isinstance(c, dict) and isinstance(c.get("key"), str):
            cols.append((c["key"], str(c.get("title") or c["key"])))
        elif isinstance(c, str):
            cols.append((c, c))
    keys = [k for k, _ in cols]
    sorts = tuple(s for s in spec.get("sorts") or [] if s in keys) or tuple(keys[:1])
    filters = {}
    for f, values in (spec.get("filters") or {}).items() if isinstance(spec.get("filters"), dict) else ():
        vals = tuple(dict.fromkeys(str(v) for v in values)) if isinstance(values, list) else ()
        filters[str(f)] = vals if vals[:1] == (ALL,) else (ALL, *[v for v in vals if v != ALL])
    return Panel(f"{slug(project)}-{slug(own)}", project, own, _texts(spec.get("title"), own), tuple(cols), sorts,
                 filters, str(spec.get("id") or "id"), rows if isinstance(rows, str) else "",
                 read if isinstance(read, str) and not rows else "", str(spec.get("help") or ""), ref)


def _tab(project: str, spec, panels: dict, notes: list) -> Tab | None:
    if not isinstance(spec, dict) or not spec.get("id"):
        notes.append(f"{project}: a tab is a mapping with an id: left out")
        return None
    for k in sorted(set(spec) - TAB_KEYS):
        notes.append(f"{project}: tab {spec['id']!r}: key {k!r} unknown to this engine: kept, not used")
    own = [f"{slug(project)}-{slug(p)}" for p in spec.get("panels") or []]
    shown = tuple(p for p in own if p in panels)
    if not shown:
        notes.append(f"{project}: tab {spec['id']!r} names no panel it declares: left out")
        return None
    name = f"{slug(project)}-{slug(spec['id'])}"
    return Tab(name, project, _texts(spec.get("label"), str(spec["id"])),
               _texts(spec.get("question"), f"What {project}'s plugin shows"), shown)


def load(projs, resolve=None) -> Plugged:
    """The panels and tabs the plugins of ``projs`` (brain.projects.Project) declare; a plugin that cannot be loaded
    is noted, never raised."""
    if resolve is None:
        from .plugins import resolve
    out = Plugged()
    for p in projs:
        ref = p.plugin.strip() if isinstance(getattr(p, "plugin", None), str) else ""
        if not ref:
            continue
        try:
            decl = declaration(resolve(ref))
        except Exception as exc:  # a plugin's own error: noted, the cockpit goes on
            out.notes.append(f"{p.name}: plugin {ref!r}: {exc}")
            continue
        if decl is None:
            continue
        panels, tabs = parse(p.name, ref, decl, out.notes)
        out.panels.update(panels)
        out.tabs.update(tabs)
    return out


def rows(panel: Panel, project, resolve=None) -> list[dict]:
    """A panel's rows for one project (brain.projects.Project), each with its project and its id; raises on a file or
    a read that fails (the cockpit keeps the panel's last content and shows the error)."""
    if panel.rows_file:
        data = json.loads((Path(project.root) / panel.rows_file).read_text(encoding="utf-8"))
    else:
        if resolve is None:
            from .plugins import resolve
        data = resolve(panel.read)(Path(project.root))
    got = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(got, list):
        raise ValueError(f"{panel.own}: rows are a list of objects, got {type(got).__name__}")
    out = []
    for i, r in enumerate(x for x in got if isinstance(x, dict)):
        ident = r.get(panel.id_field)
        out.append({**r, "project": project.name, "id": str(ident) if ident not in (None, "") else f"#{i + 1}"})
    return out


def sort_key(key: str):
    """A column's sort: numbers by value, the rest as text, an empty value last."""
    def k(r):
        v = r.get(key)
        if v is None or v == "":
            return (2, 0, "")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return (0, v, "")
        return (1, 0, str(v).lower())
    return k


def cell(value) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
