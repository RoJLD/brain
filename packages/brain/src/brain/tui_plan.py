"""The Milestones tab's Tree view in the Textual cockpit (wi-brain-tui-plan-tree; spec-brain-plan-views §3.1-§3.2,
spec-brain-cockpit-ux2 §4.3, UX-11 to UX-13): the ``plan`` panel is a Textual ``Tree`` of brain.planviews' nodes,
read from the graph and the forecast's latest.json by the cockpit's worker (brain.cockpit ``read_plan``).

Keys: ``g`` the next axis (``cockpit.MODES``: milestones, waves), ``←`` folds (or goes to the parent), ``→`` unfolds (or
goes to the first child), Enter opens a record's detail (an item's, a milestone's) and folds or unfolds a group,
``space`` stays the cockpit's pause. A refresh rebuilds the tree with the same nodes open and the cursor on the same
key; the axis is kept in tui.json with the tab's view. Under 120 columns a milestone's row drops its bar.
"""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.widgets import Tree

from . import cockpit, planviews


class PlanTree(Tree):
    """The plan panel: a node's data is its planviews node (its ``key``, ``kind``, ``id`` and ``project``)."""

    BINDINGS = [Binding("g", "app.plan_axis", "Axis"), Binding("left", "fold", "Fold", show=False),
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


def opened(nodes: list[dict]) -> set[str]:
    """The keys open at first: every node but the folded groups (the done items, the items of no milestone) and the
    milestones' items (a milestone shows its rows once unfolded), the roots and their milestones open."""
    out: set[str] = set()

    def walk(ns: list[dict], depth: int) -> None:
        for n in ns:
            if n["children"] and not n.get("fold") and (depth < 1 or n["kind"] in ("era", "group")):
                out.add(n["key"])
            walk(n["children"], depth + 1)
    walk(nodes, 0)
    return out


class PlanTreeApp:
    """CockpitApp's part for the plan panel."""

    plan_axis: str = "milestones"
    plan_open: set[str] | None = None   # the keys open, once the tree was drawn

    def _plan_init(self, tabs: dict | None) -> None:
        saved = ((tabs or {}).get("milestones") or {}).get("axis")
        self.plan_axis = cockpit.axis_of("plan", saved)
        self.plan_open = None

    def _plan_tree(self) -> PlanTree:
        return self._q("#plan", PlanTree)

    def _draw_plan(self, panel: dict | None) -> None:
        """The tree rebuilt from ``panel`` on the axis: the open nodes and the cursor's key kept."""
        tree = self._plan_tree()
        at = _cursor_key(tree)
        if self.plan_open is not None:
            self.plan_open = _open_keys(tree)
        tree.clear()
        groups = (panel or {}).get("projects") or []
        roots = [(g, (g.get("trees") or {}).get(self.plan_axis) or []) for g in groups]
        if self.plan_open is None:
            self.plan_open = {g["project"] for g, _ in roots} | {k for _, ns in roots for k in opened(ns)}
        _fill(tree, roots, max(40, tree.size.width or cockpit.NARROW_COLUMNS), self.plan_open)
        dates = groups[0]["forecast"] if len(groups) == 1 else "ranges p10–p90"
        tree.border_subtitle = f"axis: {self.plan_axis} · g axis · ←/→ fold · Enter detail · {dates}"
        target = _node_of(tree, at)
        if target is not None:   # once its lines are counted: a node's line is known after the rebuild's refresh
            self.call_after_refresh(tree.move_cursor, target)

    def action_plan_axis(self) -> None:
        """g: the tree's next axis, kept with the tab's view."""
        axes = cockpit.MODES["plan"]["axes"]
        self.plan_axis = axes[(axes.index(self.plan_axis) + 1) % len(axes)]
        self.plan_open = None   # the other axis's own defaults
        self._save()
        self._draw_plan(self.cockpit.snapshot()["panels"].get("plan"))

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Enter on a record: its detail; on a group, it folds or unfolds."""
        if not isinstance(event.control, PlanTree):
            return
        event.stop()
        node = event.node
        data = node.data or {}
        kind = data.get("kind")
        if kind == "item":
            self.open_detail("frontier", {"id": data["id"], "project": data["project"]})
        elif kind in ("milestone", "era", "wave") and data.get("id"):
            self.open_detail("milestones", {"id": data["id"], "project": data["project"], "done": data.get("done", 0),
                                            "items": data.get("items", 0), "title": data.get("title", "")})
        elif node.children:
            node.toggle()


def _nodes(root) -> list:
    out, stack = [], list(root.children)
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(n.children)
    return out


def _cursor_key(tree: PlanTree) -> str | None:
    node = tree.cursor_node
    return (node.data or {}).get("key") if node is not None else None


def _open_keys(tree: PlanTree) -> set[str]:
    return {n.data["key"] for n in _nodes(tree.root) if n.is_expanded and n.data}


def _node_of(tree: PlanTree, key: str | None):
    return next((n for n in _nodes(tree.root) if (n.data or {}).get("key") == key), None) if key else None


def _fill(tree: PlanTree, roots: list[tuple[dict, list[dict]]], width: int, open_: set[str]) -> None:
    """Each project's nodes under the tree's root; several projects: each under its own node."""
    multi = len(roots) > 1
    for g, nodes in roots:
        top = tree.root
        if multi:
            top = tree.root.add(f"{g['project']}  {g['forecast']}", data={"key": g["project"], "kind": "group"},
                                expand=g["project"] in open_)
        for n in nodes:
            _add(top, n, 0, width, open_)
    if not roots:
        tree.root.add_leaf("not read yet")


def _add(parent, n: dict, depth: int, width: int, open_: set[str]) -> None:
    text = planviews.label(n, depth, width)
    data = {k: n.get(k) for k in ("key", "kind", "id", "project", "done", "items", "title")}
    if not n["children"]:
        parent.add_leaf(text, data=data)
        return
    node = parent.add(text, data=data, expand=n["key"] in open_)
    for c in n["children"]:
        _add(node, c, depth + 1, width, open_)
