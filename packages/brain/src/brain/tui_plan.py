"""The Milestones tab's Tree and Trajectories views in the Textual cockpit (wi-brain-tui-plan-tree,
wi-brain-tui-trajectories-bands; spec-brain-plan-views §3.1-§3.3, spec-brain-cockpit-ux2 §4.3, UX-11 to UX-13): the
``plan`` panel is a Textual ``Tree`` of brain.planviews' nodes, and its ``traj`` frame an ``OptionList`` of
brain.planbands' rows, both read from the graph and the forecast's latest.json by the cockpit's worker
(brain.cockpit ``read_plan``).

Tree keys: ``g`` the next axis (``cockpit.MODES``: milestones, waves), ``f`` the P0 and P1 items alone (again: all,
wi-brain-tui-waves), ``←`` folds (or goes to the parent), ``→`` unfolds (or goes to the first child), Enter opens an
item's detail, a milestone's row in Trajectories (its detail when the forecast has no row for it) and folds or unfolds
a group or a lot, ``space`` stays the cockpit's pause. A refresh rebuilds the tree with the same nodes open and the
cursor on the same key, and the sessions read again redraw it when the session on an item changed; the axis is kept in
tui.json with the tab's view. Under 120 columns a milestone's row drops its bar.

Trajectories keys: ``[`` a finer scale, ``]`` a coarser one (days a cell, ``planbands.SCALES``), ``←``/``→`` pan a week,
Enter a milestone's detail; a refresh keeps the scale, the pan and the cursor's row.
"""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.widgets import OptionList, Tree
from textual.widgets.option_list import Option

from . import cockpit, planbands, planviews

MILESTONE_KINDS = ("milestone", "era", "wave")


class PlanTree(Tree):
    """The plan panel: a node's data is its planviews node (its ``key``, ``kind``, ``id`` and ``project``)."""

    BINDINGS = [Binding("g", "app.plan_axis", "Axis"), Binding("f", "app.plan_urgent", "P0/P1"),
                Binding("left", "fold", "Fold", show=False),
                Binding("right", "unfold", "Unfold", show=False), Binding("space", "app.pause", "Pause", show=False)]

    def __init__(self, **kw) -> None:
        super().__init__("plan", **kw)
        self.show_root = False
        self.guide_depth = planviews.GUIDE
        self.auto_expand = False   # Enter opens a record's detail; a group folds and unfolds (PlanTreeApp)

    def process_label(self, label):
        """A row is plain text, never markup: a title may hold brackets."""
        return Text(label) if isinstance(label, str) else label

    def action_fold(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded and node.children:
            node.collapse()
        elif node.parent is not None and node.parent is not self.root:
            self.move_cursor(node.parent)

    def action_unfold(self) -> None:
        node = self.cursor_node
        if node is None or not node.children:
            return
        if not node.is_expanded:
            node.expand()
        else:
            self.move_cursor(node.children[0])


class TrajView(OptionList):
    """The traj frame: a row per milestone, era and wave as a band (brain.planbands), the dates' row and each project's
    heading disabled; its scale, pan and cursor kept across refreshes."""

    BINDINGS = [Binding("left_square_bracket", "scale(-1)", "Finer", key_display="["),
                Binding("right_square_bracket", "scale(1)", "Coarser", key_display="]"),
                Binding("left", "pan(-1)", "Earlier", show=False), Binding("right", "pan(1)", "Later", show=False)]

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.scale: float | None = None   # None: planbands.default_scale at the frame's width
        self.pan_at = 0
        self.panel: dict | None = None
        self.rows: dict[str, dict] = {}
        self.at: str | None = None        # the row to put the cursor on at the next draw (Enter on a Tree milestone)

    def _width(self) -> int:
        return max(60, (self.scrollable_content_region.width or self.size.width or cockpit.NARROW_COLUMNS) - 1)

    def show(self, panel: dict | None) -> None:
        """The rows of ``panel`` at the frame's width, the cursor on the same row (or on ``at``)."""
        self.panel = panel
        key = self.at or _option_id(self)
        options, self.rows = traj_options(panel, self._width(), self.scale, self.pan_at)
        self.clear_options()
        self.add_options(options)
        index = next((k for k, o in enumerate(options) if key and o.id == key), None)
        if index is None:
            index = next((k for k, o in enumerate(options) if not o.disabled), None)
        self.highlighted = index
        self.at = None
        self.border_subtitle = planbands.legend(planviews.words())

    def action_scale(self, step: int) -> None:
        old = self.scale or planbands.default_scale(planbands.cells(self._width()))
        self.scale = planbands.zoom(old, step)
        self.pan_at = planbands.rescaled(self.pan_at, old, self.scale)
        self.show(self.panel)

    def action_pan(self, step: int) -> None:
        scale = self.scale or planbands.default_scale(planbands.cells(self._width()))
        self.pan_at = planbands.pan(self.pan_at, scale, step)
        self.show(self.panel)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter on a milestone's, an era's or a wave's row: its detail."""
        event.stop()
        r = self.rows.get(event.option.id or "")
        if r and r["kind"] in MILESTONE_KINDS:
            self.app.open_detail("milestones", {"id": r["id"], "project": r["project"], "done": r.get("done", 0),
                                                "items": r.get("items", 0), "title": r.get("title", "")})


def _option_id(view: OptionList) -> str | None:
    if view.highlighted is None or view.highlighted >= view.option_count:
        return None
    return view.get_option_at_index(view.highlighted).id


def traj_options(panel: dict | None, width: int, scale: float | None, offset: int) -> tuple[list[Option], dict]:
    """The frame's options: per project its heading (with several), its dates' row, then its rows; {key: row}."""
    groups = (panel or {}).get("projects") or []
    options, rows = [], {}
    for g in groups:
        b = g.get("bands") or {}
        if len(groups) > 1 or "error" in g or not b.get("rows"):
            text = f"error: {g['error']}" if "error" in g else b.get("heading", "")
            options.append(Option(Text(f"{g['project']}: {text}" if len(groups) > 1 else text), disabled=True))
        if not b.get("rows") and not b.get("tail"):
            continue
        head, drawn = planbands.chart(b, width, scale, offset)
        options.append(Option(Text(head), disabled=True))
        for r, text in drawn:
            options.append(Option(Text(text), id=r["key"]))
            rows[r["key"]] = r
    if not groups:
        options.append(Option(Text("not read yet"), disabled=True))
    return options, rows


def band_keys(panel: dict | None) -> set[str]:
    """The keys of the rows the Trajectories show: a Tree milestone with one opens there."""
    return {r["key"] for g in (panel or {}).get("projects") or [] for r in (g.get("bands") or {}).get("rows") or []}


def opened(nodes: list[dict]) -> set[str]:
    """The keys open at first: every node but the folded groups (the done items, the items of no milestone) and the
    milestones' items (a milestone shows its rows once unfolded), the roots and their milestones open, a wave's lots
    open (a wave unfolded shows its items in their lots)."""
    out: set[str] = set()

    def walk(ns: list[dict], depth: int) -> None:
        for n in ns:
            if n["children"] and not n.get("fold") and (depth < 1 or n["kind"] in ("era", "group", "lot")):
                out.add(n["key"])
            walk(n["children"], depth + 1)
    walk(nodes, 0)
    return out


class PlanTreeApp:
    """CockpitApp's part for the plan panel."""

    plan_axis: str = "milestones"
    plan_open: set[str] | None = None   # the keys open, once the tree was drawn
    plan_urgent: bool = False           # f: the P0 and P1 items alone
    plan_working: dict[str, str] | None = None   # {item: the live session on it} the tree was drawn with

    def _plan_init(self, tabs: dict | None) -> None:
        saved = ((tabs or {}).get("milestones") or {}).get("axis")
        self.plan_axis = cockpit.axis_of("plan", saved)
        self.plan_open = None
        self.plan_urgent = False

    def _plan_tree(self) -> PlanTree:
        return self._q("#plan", PlanTree)

    def _draw_plan(self, panel: dict | None) -> None:
        """The tree rebuilt from ``panel`` on the axis (``f``: its P0 and P1 items alone), each item's live session
        from the sessions panel: the open nodes and the cursor's key kept."""
        tree = self._plan_tree()
        at = _cursor_key(tree)
        if self.plan_open is not None:
            self.plan_open = _remembered(tree, self.plan_open)
        tree.clear()
        groups = (panel or {}).get("projects") or []
        roots = [(g, _shown_nodes((g.get("trees") or {}).get(self.plan_axis) or [], self.plan_urgent)) for g in groups]
        if self.plan_open is None and roots:   # the defaults once there is a tree: an empty first read keeps them
            self.plan_open = _first_open(roots)
        self.plan_working = planviews.sessions_of(self.cockpit.snapshot()["panels"].get("sessions"))
        _fill(tree, roots, max(40, tree.size.width or cockpit.NARROW_COLUMNS), self.plan_open or set(),
              self.plan_working)
        tree.border_subtitle = _subtitle(self.plan_axis, self.plan_urgent, groups)
        target = _node_of(tree, at)
        if target is not None:   # once its lines are counted: a node's line is known after the rebuild's refresh
            self.call_after_refresh(tree.move_cursor, target)

    def action_plan_urgent(self) -> None:
        """f: the P0 and P1 items alone, and what holds them; again: every item."""
        self.plan_urgent = not self.plan_urgent
        self._draw_plan(self.cockpit.snapshot()["panels"].get("plan"))

    def _plan_sessions(self, panels: dict) -> None:
        """The sessions read again: the tree redrawn when the session on an item changed."""
        if self.plan_working is not None and planviews.sessions_of(panels.get("sessions")) != self.plan_working:
            self._draw_plan(panels.get("plan"))

    def action_plan_axis(self) -> None:
        """g: the tree's next axis, kept with the tab's view."""
        axes = cockpit.MODES["plan"]["axes"]
        self.plan_axis = axes[(axes.index(self.plan_axis) + 1) % len(axes)]
        self.plan_open = None   # the other axis's own defaults
        self._save()
        self._draw_plan(self.cockpit.snapshot()["panels"].get("plan"))

    def _draw_traj(self, panel: dict | None) -> None:
        self._q("#traj", TrajView).show(panel)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Enter on an item: its detail; on a milestone, its row in Trajectories (its detail when the forecast has no
        row for it); on a group, it folds or unfolds."""
        if not isinstance(event.control, PlanTree):
            return
        event.stop()
        node = event.node
        data = node.data or {}
        kind = data.get("kind")
        if kind == "item":
            self.open_detail("frontier", {"id": data["id"], "project": data["project"]})
        elif kind in MILESTONE_KINDS and data.get("id"):
            self._open_milestone(data)
        elif node.children:
            node.toggle()

    def _open_milestone(self, data: dict) -> None:
        if data.get("key") in band_keys(self.cockpit.snapshot()["panels"].get("plan")):
            self._q("#traj", TrajView).at = data["key"]
            self.action_set_view("trajectories")
            return
        self.open_detail("milestones", {"id": data["id"], "project": data["project"], "done": data.get("done", 0),
                                        "items": data.get("items", 0), "title": data.get("title", "")})


def _nodes(root) -> list:
    out, stack = [], list(root.children)
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(n.children)
    return out


def _first_open(roots: list[tuple[dict, list[dict]]]) -> set[str]:
    """The keys open at first: each project's node and ``opened``'s."""
    return {g["project"] for g, _ in roots} | {k for _, ns in roots for k in opened(ns)}


def _cursor_key(tree: PlanTree) -> str | None:
    node = tree.cursor_node
    return (node.data or {}).get("key") if node is not None else None


def _open_keys(tree: PlanTree) -> set[str]:
    return {n.data["key"] for n in _nodes(tree.root) if n.is_expanded and n.data}


def _node_of(tree: PlanTree, key: str | None):
    return next((n for n in _nodes(tree.root) if (n.data or {}).get("key") == key), None) if key else None


def _shown_nodes(nodes: list[dict], urgent: bool) -> list[dict]:
    return planviews.only(nodes) if urgent else nodes


def _remembered(tree: PlanTree, before: set[str]) -> set[str]:
    """The keys open now; the nodes not drawn (f hid them) keep what was remembered of them."""
    drawn = {n.data["key"] for n in _nodes(tree.root) if n.data}
    return _open_keys(tree) | (before - drawn)


def _subtitle(axis: str, urgent: bool, groups: list[dict]) -> str:
    dates = groups[0]["forecast"] if len(groups) == 1 else "ranges p10–p90"
    only = "P0/P1 only · f all" if urgent else "f P0/P1 only"
    return f"axis: {axis} · g axis · {only} · ←/→ fold · Enter detail · {dates}"


def _fill(tree: PlanTree, roots: list[tuple[dict, list[dict]]], width: int, open_: set[str],
          working: dict[str, str] | None = None) -> None:
    """Each project's nodes under the tree's root; several projects: each under its own node; ``working`` {item: its
    live session}."""
    multi = len(roots) > 1
    for g, nodes in roots:
        top = tree.root
        if multi:
            top = tree.root.add(f"{g['project']}  {g['forecast']}", data={"key": g["project"], "kind": "group"},
                                expand=g["project"] in open_)
        for n in nodes:
            _add(top, n, 0, width, open_, working or {})
    if not roots:
        tree.root.add_leaf("not read yet")


def _add(parent, n: dict, depth: int, width: int, open_: set[str], working: dict[str, str]) -> None:
    text = planviews.label(n, depth, width, working=working)
    data = {k: n.get(k) for k in ("key", "kind", "id", "project", "done", "items", "title")}
    if not n["children"]:
        parent.add_leaf(text, data=data)
        return
    node = parent.add(text, data=data, expand=n["key"] in open_)
    for c in n["children"]:
        _add(node, c, depth + 1, width, open_, working)
