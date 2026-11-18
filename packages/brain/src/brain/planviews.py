"""The plan views of the cockpit's Milestones tab (wi-brain-tui-plan-tree; spec-brain-plan-views §3.1, §3.2 and §3.6;
VIZ-1, VIZ-2): the Tree, the backlog's WBS on two axes, read at zero token from the graph and the forecast's
``<BRAIN_HOME>/forecast/<project>/latest.json``, never recomputed.

  milestones  era > milestone (> its sub-milestones) > item: the eras first, then « (no era) » with the milestones of
              no era, then « (no milestone) » with the open items of no thematic milestone (a wave's alone included,
              wi-brain-forecast-two-parents);
  waves       era > wave > item: a wave is a milestone of kind wave (brain.waves), in its release's order, then
              « (no wave) » with the open items of no wave.

A milestone's row: its items done out of its live items, counted through its sub-milestones
(``resume.Store.milestone_items``), its bar, its p10-p90 from the forecast (« reached » and its day once reached; held
undated by a gate, why). An item's row: its state (``●`` doing, ``○`` todo, ``⊘`` blocked, ``◌`` deferred, ``✓`` done),
its priority, its gates (``⧗`` a pending DDR, ``⚑`` an owner's action, ``⇢`` another project, ``⊘`` undated, why) and
its own band. Done items fold under « ✓ N done », so the open ones come first. The glyphs carry the meaning without
colour (NO_COLOR); the legacy console (``TERM=linux``) gets words (UX-13). No forecast: « no forecast yet: brain
forecast ».

The axes are data (``brain.cockpit.MODES``): ``tree(st, fc, axis)`` gives the nodes ``{key, kind, id, name, ...,
children}`` the Textual ``Tree`` shows (brain.tui) and ``lines`` prints (``brain tui --once --tab milestones --view
tree [--axis waves]``), from the same function.
"""

from __future__ import annotations

import os
import re
from datetime import date

from . import forecast, resume, waves

AXES = ("milestones", "waves")
WAVE, ERA = "wave", "era"
GUIDE = 4            # the columns a level indents: the Tree's guide and the text's « ├── »
NAME_W = 40          # a root's name column; each level takes GUIDE off it
BAR_W = 10
WIDE = 120           # under it the bar is left out
STATES = {"doing": "●", "todo": "○", "blocked": "⊘", "deferred": "◌", "done": "✓", "dropped": "✗"}
PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
STATE_ORDER = {"doing": 0, "todo": 1, "blocked": 2, "deferred": 3}
GATES = {"ddr": ("⧗", "DDR"), "action": ("⚑", "action"), "outside": ("⇢", "other project"),
         "undated": ("⊘", "undated")}
_RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def words() -> bool:
    """The legacy console (``TERM=linux``): words instead of glyphs (UX-13)."""
    return os.environ.get("TERM") == "linux"


def _kind(n: dict) -> str:
    return str((n.get("props") or {}).get("kind") or "")


def _md(day: str) -> str:
    try:
        d = date.fromisoformat(str(day)[:10])
    except ValueError:
        return ""
    return f"{d:%b} {d.day}"


def heading(fc: dict | None) -> str:
    """What the forecast says of the dates: its day and its calibration, or that there is none."""
    if not fc:
        return "no forecast yet: brain forecast"
    cal = (fc.get("calibration") or {})
    tag = ("calibrated" if cal.get("state") == "calibrated" else
           f"UNCALIBRATED ({cal.get('judged', 0)} of {cal.get('needed', forecast.CALIBRATED_MIN)} judged)")
    return f"ranges p10–p90 {tag}, forecast of {str(fc.get('as_of') or '')[:16].replace('T', ' ')} UTC"


def _calibrated(fc: dict | None) -> bool:
    return bool(fc) and (fc.get("calibration") or {}).get("state") == "calibrated"


def _when_milestone(m: dict, fc: dict | None) -> str:
    """A milestone's dates: reached and its day, the forecast's range, or why it has none."""
    if m.get("status") == "reached":
        return f"reached {_md(str((m.get('props') or {}).get('reached') or ''))}".strip()
    f = _forecast_of(m["id"], fc)
    if not f:
        return ""
    if f.get("shown") == "undated":
        return _undated(f)
    return forecast.span(f, _calibrated(fc)) if f.get("dates") else ("all done" if not f.get("open") else "no date")


def _undated(f: dict) -> str:
    """Why the forecast gives a milestone no date: its own gate, or its items it cannot date."""
    if f.get("held"):
        return f"undated: {forecast.gate_kind(f['held'])}"
    n = len(f.get("undated") or [])
    return f"undated: {n} item(s) not dated" if n else "undated"


def _item_forecast(fc: dict | None) -> tuple[dict, dict]:
    if not fc:
        return {}, {}
    items = {i["id"]: i for i in fc.get("items") or [] if i.get("id")}
    undated = {u["id"]: u.get("why") or "" for u in (fc.get("gates") or {}).get("undated") or [] if u.get("id")}
    return items, undated


def _item(st: resume.Store, nid: str, items: dict, undated: dict, cal: bool, project: str) -> dict:
    n = st.nodes.get(nid) or {}
    props = n.get("props") or {}
    status = str(n.get("status") or "")
    prio = str(props.get("priority") or "") or (f"{props['priority_proposed']}?" if props.get("priority_proposed")
                                                 else "")
    gates, when = _item_when(status, props, items.get(nid) or {}, undated.get(nid), cal)
    return {"key": f"{project}:{nid}", "kind": "item", "id": nid, "project": project, "name": nid,
            "title": str(n.get("title") or ""), "state": status, "priority": prio, "gates": gates, "when": when,
            "children": []}


def _item_when(status: str, props: dict, f: dict, why: str | None, cal: bool) -> tuple[list[str], str]:
    """An item's gates and band: done and its day; undated and why (``why``: the forecast's reason); its range."""
    gates = (["ddr"] if f.get("ddr") else []) + (["action"] if f.get("action") else [])
    if status == "done":
        return gates, f"done {_md(str(props.get('done') or ''))}".strip()
    if why is not None:
        kind = forecast.gate_kind(why)
        return gates + ["outside" if kind == "after another project" else "undated"], f"undated: {kind}"
    if f.get("dates"):
        return gates, forecast.span({"dates": f["dates"], "shown": forecast._shown(f.get("days"))}, cal)
    return gates, ""


def _item_order(x: dict) -> tuple:
    p = x["priority"].rstrip("?")
    return (STATE_ORDER.get(x["state"], 9), PRIORITY.get(p, 8), x["priority"].endswith("?"), x["id"])


def _links(st: resume.Store, axis: str) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """({milestone: the work items directly part of it}, {milestone: the milestones part of it}), in one pass; on the
    waves axis an open item carried out of a closed wave sits in the wave it is in now (brain.waves' ``wave_of``)."""
    items: dict[str, set[str]] = {}
    subs: dict[str, set[str]] = {}
    plan = waves.Plan(st.nodes)
    for e in st.edges:
        src, dst = e.get("from"), e.get("to")
        if e.get("type") != "part_of" or (st.nodes.get(dst) or {}).get("type") != "Milestone":
            continue
        kind = (st.nodes.get(src) or {}).get("type")
        if kind == "WorkItem":
            items.setdefault(dst, set()).add(src)
            plan.parents[src].append(dst)
        elif kind == "Milestone":
            subs.setdefault(dst, set()).add(src)
    if axis == "waves":
        for n in st.of_type("WorkItem"):
            if (n.get("props") or {}).get("carried_to") and n.get("status") in (*resume.WORK_OPEN, "deferred"):
                now = plan.wave_of(n["id"])
                for w in plan.planned(n["id"]):
                    items.get(w, set()).discard(n["id"])
                if now:
                    items.setdefault(now, set()).add(n["id"])
    return items, subs


class _Ctx:
    """What building one project's tree on one axis reads: the store, the forecast and the links."""

    def __init__(self, st: resume.Store, fc: dict | None, axis: str, project: str) -> None:
        self.st, self.fc, self.axis, self.project = st, fc, axis, project
        self.items, self.undated = _item_forecast(fc)
        self.cal = _calibrated(fc)
        self.members, self.subs = _links(st, axis)
        self.seen: set[str] = set()

    def keep(self, n: dict) -> bool:
        """The milestones of the axis: waves on the waves axis, the others on the milestones axis; eras on both."""
        return (_kind(n) == WAVE) == (self.axis == "waves") or _kind(n) == ERA

    def sub_milestones(self, mid: str) -> list[str]:
        return sorted(s for s in self.subs.get(mid, ()) if (self.st.nodes.get(s) or {}).get("status") != "dropped"
                      and self.keep(self.st.nodes[s]) and s not in self.seen)

    def item(self, nid: str) -> dict:
        return _item(self.st, nid, self.items, self.undated, self.cal, self.project)


def _release(n: dict) -> tuple:
    m = _RELEASE.match(str((n.get("props") or {}).get("release") or ""))
    return tuple(int(x) for x in m.groups()) if m else (9999,)


def _short(mid: str, project: str) -> str:
    for pre in (f"ms-{project}-", "ms-", f"era-{project}-", f"wave-{project}-"):
        if mid.startswith(pre):
            return mid[len(pre):]
    return mid


def _milestone(c: _Ctx, mid: str) -> dict:
    st, project, fc = c.st, c.project, c.fc
    n = st.nodes[mid]
    # a wave counts the items in it now (one carried out of it counts in the wave it went to); else through its subs
    of = c.members.get(mid, ()) if _kind(n) == WAVE and c.axis == "waves" else st.milestone_items(mid)
    live = [i for i in of if st.status(i) != "dropped"]
    kind = _kind(n) or "milestone"
    node = {"key": f"{project}:{mid}", "kind": kind, "id": mid, "project": project, "name": _name(n, kind, project),
            "title": str(n.get("title") or ""), "state": str(n.get("status") or ""),
            "done": sum(1 for i in live if st.status(i) == "done"), "items": len(live),
            "when": _when_milestone(n, fc), "gates": _milestone_gates(mid, fc), "p10": _p10(mid, fc), "children": []}
    c.seen.add(mid)
    subs = [_milestone(c, s) for s in c.sub_milestones(mid) if s not in c.seen]
    node["children"] += sorted(subs, key=lambda x: _milestone_order(x, st))
    own = [c.item(i) for i in sorted(c.members.get(mid, ())) if st.status(i) != "dropped"]
    node["children"] += _items_folded(own, project, mid)
    return node


def _name(n: dict, kind: str, project: str) -> str:
    """An era by its id, a wave by its release and id (« 0.6.0 (wave-s7) »), a milestone by its short id."""
    mid = n["id"]
    if kind == ERA:
        return mid
    if kind == WAVE:
        release = str((n.get("props") or {}).get("release") or "")
        return f"{release} ({mid})" if release and release != mid else mid
    return _short(mid, project)


def _forecast_of(mid: str, fc: dict | None) -> dict:
    return next((x for x in (fc or {}).get("milestones") or [] if x.get("id") == mid), None) or {}


def _milestone_gates(mid: str, fc: dict | None) -> list[str]:
    return list(_forecast_of(mid, fc).get("gates") or [])


def _p10(mid: str, fc: dict | None) -> str:
    return str((_forecast_of(mid, fc).get("dates") or {}).get("p10") or "")


def _milestone_order(x: dict, st: resume.Store) -> tuple:
    """Waves in their release's order; else the pending ones by the forecast's p10 (undated after), the reached last."""
    if x["kind"] == WAVE:
        return (0, _release(st.nodes[x["id"]]), "", x["id"])
    return (1 + (x["state"] == "reached"), (), x.get("p10") or "9999", x["id"])


def _items_folded(rows: list[dict], project: str, parent: str) -> list[dict]:
    """The open items first, in their order, then the done ones folded under « ✓ N done »."""
    open_ = sorted((r for r in rows if r["state"] != "done"), key=_item_order)
    done = sorted((r for r in rows if r["state"] == "done"), key=lambda r: r["id"])
    if done:
        open_.append({"key": f"{project}:{parent}:done", "kind": "done", "id": "", "project": project,
                      "name": f"{len(done)} done", "fold": True, "children": done})
    return open_


def tree(st: resume.Store, fc: dict | None, axis: str = "milestones", project: str = "") -> list[dict]:
    """The roots of one project's tree on ``axis`` (``AXES``): its eras, then the group of no era, then the open items
    of no milestone (of no wave, on the waves axis); each node ``{key, kind, id, project, name, ..., children}``,
    ``fold`` on the groups the tree shows folded."""
    if axis not in AXES:
        raise ValueError(f"{axis}: one of {', '.join(AXES)}")
    c = _Ctx(st, fc, axis, project)
    ms = {m["id"]: m for m in st.of_type("Milestone") if m.get("status") != "dropped"}
    roots = [_milestone(c, e["id"]) for e in sorted((m for m in ms.values() if _kind(m) == ERA), key=lambda m: m["id"])]
    what = "wave" if axis == "waves" else "milestone"
    rows = _no_era(c, ms)
    if rows:
        roots.append(_group(project, "(no era)", f"{len(rows)} {what}(s)", rows, fold=False))
    stray = _stray(c, ms)
    if stray:
        roots.append(_group(project, f"(no {what})", f"{len(stray)} open item(s)", stray, fold=True))
    return roots


def _no_era(c: _Ctx, ms: dict[str, dict]) -> list[dict]:
    """The milestones of the axis under no era nor any other of its milestones, in their order."""
    held = {s for m, ss in c.subs.items() if m in ms and c.keep(ms[m]) for s in ss}
    rows = [_milestone(c, m["id"]) for m in sorted(ms.values(), key=lambda m: m["id"])
            if m["id"] not in c.seen and _kind(m) != ERA and c.keep(m) and m["id"] not in held]
    return sorted(rows, key=lambda x: _milestone_order(x, c.st))


def _stray(c: _Ctx, ms: dict[str, dict]) -> list[dict]:
    """The open items in no milestone of the axis, in their order."""
    homed = {i for m in ms.values() if c.keep(m) for i in c.members.get(m["id"], ())}
    return sorted((c.item(n["id"]) for n in c.st.of_type("WorkItem")
                   if n.get("status") in (*resume.WORK_OPEN, "deferred") and n["id"] not in homed), key=_item_order)


def _group(project: str, name: str, count: str, children: list[dict], fold: bool) -> dict:
    return {"key": f"{project}:{name}", "kind": "group", "id": "", "project": project, "name": f"{name}  {count}",
            "fold": fold, "children": children}


def collect(st: resume.Store, fc: dict | None, project: str) -> dict:
    """One project's part of the cockpit's ``plan`` panel: the forecast's heading and the tree on each axis."""
    return {"project": project, "forecast": heading(fc), "as_of": (fc or {}).get("as_of"),
            "trees": {a: tree(st, fc, a, project) for a in AXES}}


# --- the labels, shared by the Textual Tree and the text twin ---

def bar(done: int, total: int, width: int = BAR_W) -> str:
    full = round(width * done / total) if total else 0
    return "█" * full + "░" * (width - full)


def _glyph(state: str, plain: bool) -> str:
    return state if plain else STATES.get(state, "·")


def label(node: dict, depth: int = 0, width: int = WIDE, plain: bool | None = None) -> str:
    """A node's row, its columns aligned at ``depth`` (each level indents ``GUIDE``): a milestone's name, counts, bar
    (from ``WIDE`` columns) and dates; an item's state, priority, id, gates and band; a group's name."""
    plain = words() if plain is None else plain
    name_w = max(12, NAME_W - GUIDE * depth)
    kind = node["kind"]
    if kind == "group":
        return node["name"]
    if kind == "done":
        return ("done " if plain else "✓ ") + node["name"]
    if kind == "item":
        return _item_label(node, name_w, plain)
    return _milestone_label(node, name_w, width, plain)


def _item_label(node: dict, name_w: int, plain: bool) -> str:
    gates = " ".join((g if plain else GATES[g][0] + " " + GATES[g][1]) for g in node["gates"])
    head = f"{_glyph(node['state'], plain)} {node['priority'] or '-':<3} {node['name']}"
    text = f"{head:<{name_w + 12}}  {node['state']:<8} {gates}".rstrip()
    return f"{text}  {node['when']}" if node["when"] else text


def _milestone_label(node: dict, name_w: int, width: int, plain: bool) -> str:
    mark = ("reached " if plain else "✓ ") if node["state"] == "reached" else ""
    counts = f"{node['done']:>3}/{node['items']:<3}"
    cols = [f"{mark}{node['name']}"[:name_w].ljust(name_w), counts]
    if width >= WIDE:
        share = round(100 * node["done"] / node["items"]) if node["items"] else 0
        cols.append(f"{share:>3} %" if plain else bar(node["done"], node["items"]))
    cols.append(node["when"])
    if node.get("gates"):
        cols.append(("gate " if plain else "⧗ ") + ", ".join(node["gates"]))
    return "  ".join(c for c in cols if c).rstrip()


def lines(panel: dict | None, axis: str = "milestones", width: int = WIDE, plain: bool | None = None) -> list[str]:
    """The text twin: the heading, then each project's tree drawn with ``├──`` and ``└──``; a folded group shows its
    row alone (the done items, the items of no milestone)."""
    plain = words() if plain is None else plain
    groups = (panel or {}).get("projects") or []
    out = [f"Milestones · Tree · axis: {axis}"]
    for g in groups:
        if "error" in g:
            out.append(f"  {g['project']}: error: {g['error']}")
            continue
        head = f"  {g['project']}: {g['forecast']}" if len(groups) > 1 else f"  {g['forecast']}"
        out.append(head)
        nodes = (g.get("trees") or {}).get(axis) or []

        def walk(ns: list[dict], prefix: str, depth: int) -> None:
            for k, n in enumerate(ns):
                last = k == len(ns) - 1
                fold = n.get("fold") and n["children"]
                arrow = ("+ " if fold else "- " if n["children"] else "  ") if plain else (
                    "▸ " if fold else "▾ " if n["children"] else "")
                branch = ("`-- " if last else "|-- ") if plain else ("└── " if last else "├── ")
                text = f"{prefix}{branch}{arrow}{label(n, depth, width, plain)}"
                out.append(text[:width].rstrip())
                if n["children"] and not fold:
                    walk(n["children"], prefix + ("    " if last else ("|   " if plain else "│   ")), depth + 1)
        walk(nodes, "  ", 0)
    if not groups:
        out.append("  no project read yet")
    return out
