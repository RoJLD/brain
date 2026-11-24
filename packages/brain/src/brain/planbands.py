"""The Trajectories view of the cockpit's Milestones tab, milestone level: the Gantt as bands
(wi-brain-tui-trajectories-bands; spec-brain-plan-views §3.3 and §3.6; VIZ-1), read at zero token from the forecast's
``<BRAIN_HOME>/forecast/<project>/latest.json``, never recomputed.

One row per milestone, era and wave the forecast dates, sorted by its median; then « (no milestone) » and the backlog.
A row's cells, at ``scale`` days a cell from the forecast's day, ``offset`` cells panned:

  ``▒``  p10 to p80;   ``░``  p80 to p90;   ``█``  the median;
  ``▸``  the band goes on beyond the ``forecast.HORIZON_DAYS`` horizon, where the forecast gives no date (PSY-2: the
         order only).

A milestone the forecast cannot date shows its dated part's band, if any, and why (its own gate, its items not dated,
by kind); its gates follow the band (``◆`` go/no-go, ``⧗`` calendar, ``⚙`` hardware, ``⇢`` another project, ``#`` a
count), and a trigger that names a duration with no gate is said not modelled. The backlog's row is its flow
(``fc["flow"]``): while it grows faster than it empties, no band. A row's notes start after its band's last mark (a
row of no band: after its open items), and wrap under themselves rather than pass the width. The heading says
UNCALIBRATED until the calibration judges enough milestones. The shapes carry the meaning without colour (NO_COLOR); the legacy console (``TERM=linux``)
gets ASCII and words (UX-13).

``collect(st, fc, project)`` gives the rows the Textual view (brain.tui_plan ``TrajView``) and the text twin
(``lines``: ``brain tui --once --tab milestones --view trajectories``) draw with ``chart``, from the same function.

The item level (wi-brain-tui-trajectories-items, §3.4; ``z`` or Enter on a row, ``--zoom <milestone>`` in the text
twin): a milestone's, an era's or a wave's items as Gantt lanes, a wave's in its lots (as the Tree's waves axis cuts
them, brain.lots), the others in the scheduler's order (the forecast's), then the items it cannot date and the done
ones. Each item's row:

  ``past``    left of ``│``, at the same scale: its actual bar ``━`` from its first session to its done day (or to the
              forecast's day while doing), from the forecast's ``past`` (the cost ledger's); done before the window,
              « ✓ <day> » (« ok <day> » in words: either fits the ``PAST_W`` cells);
  future      its start-to-finish band: ``░`` from its start's p10 to its median and from its finish's p80 to its p90,
              ``▒`` from its start's median to its finish's p80, ``█`` its finish's median (a model-2 forecast keeps
              no start: its finish band alone, as a milestone's); « ┄┄ undated: why » when the forecast cannot date it;
  ``est. h``  its drawn hours p10-p90 (a done item: its actual hours, « act »);
  ``crit.``   its criticality index for the scope (forecast ``critical``): the share of futures in which it lies on
              the chain that sets the scope's finish; ``◆`` marks the scope's most frequent chain (``c`` in the app,
              always in the text twin), whose line the heading carries.

``levels(st, fc, project, trees, rows)`` gives each banded row's level; ``item_chart`` draws one, ``zoom_lines`` is
its text twin.
"""

from __future__ import annotations

import math
import textwrap
from datetime import datetime, timedelta

from . import forecast, planviews, waves

NAME_W = 22          # a row's name column
OPEN_W = 4           # its open items
NOTE_W = 34          # the room kept right of the chart for the notes of a band that reaches its end
WRAP_MIN = 16        # less room than this right of a row's cells: its notes wrap under the cells
MIN_CELLS = 20
SCALES = (0.25, 0.5, 1, 2, 3, 7)   # days a cell: [ finer, ] coarser
PAN_DAYS = 7         # ←/→ pan a week
GLYPHS = {"inner": "▒", "outer": "░", "median": "█", "beyond": "▸"}
WORDS = {"inner": "=", "outer": "-", "median": "#", "beyond": ">"}
GATES = (("go/no-go", "◆"), ("calendar", "⧗"), ("hardware", "⚙"), ("external", "⇢"), ("count", "#"))


def _horizon() -> float:
    return float(forecast.HORIZON_DAYS)


def heading(fc: dict | None) -> str:
    """The forecast's day and calibration (planviews.heading), and what the horizon means."""
    head = planviews.heading(fc)
    return f"{head} · beyond {forecast.HORIZON_DAYS // 7} weeks: order only" if fc else head


# --- the rows: data ---

def _name(st, plan: waves.Plan, mid: str, project: str) -> tuple[str, str]:
    """(kind, name): an era by its id, a wave by « wave <release> », a milestone by its short id."""
    n = st.nodes.get(mid) or {}
    kind = planviews._kind(n) or "milestone"
    if kind == planviews.WAVE:
        release = plan.label(mid)
        return kind, f"wave {release}" if release else mid
    return kind, mid if kind == planviews.ERA else planviews._short(mid, project)


def _gate_note(text: str) -> dict:
    glyph = next((g for pre, g in GATES if text.startswith(pre)), "?")
    return {"glyph": glyph, "text": text}


def _why(ids: list[str], undated: list[dict]) -> str:
    return forecast._kinds(ids, undated) or f"{len(ids)} item(s)"


def _notes(m: dict, undated: list[dict]) -> list[dict]:
    """What follows a milestone's band: why it is not dated, its gates, a duration its trigger names and no gate
    models, its band beyond the horizon."""
    out = []
    if m.get("shown") == "undated":
        why = ", ".join(x for x in (forecast.gate_kind(m["held"]) if m.get("held") else "",
                                    _why(m["undated"], undated) if m.get("undated") else "") if x) or "undated"
        part = ((m.get("part") or {}).get("days"))
        out.append({"glyph": "⊘", "text": f"dated part only: {why}" if part else f"not dated: {why}"})
    elif not m.get("open") and not m.get("days"):
        out.append({"glyph": "", "text": "no open item: its trigger decides"})
    out += [_gate_note(g) for g in m.get("gates") or ()]
    if m.get("durations"):
        out.append({"glyph": "⧗", "text": f"{', '.join(m['durations'])} (not modelled)"})
    return out


def _band(block: dict) -> tuple[dict | None, bool]:
    """(the days drawn, whether they are the dated part only)."""
    if block.get("days"):
        return block["days"], False
    part = (block.get("part") or block.get("frozen") or {}).get("days")
    return part, bool(part)


def _row(st, plan: waves.Plan, m: dict, project: str, undated: list[dict]) -> dict:
    kind, name = _name(st, plan, m["id"], project)
    days, part = _band(m)
    return {"key": f"{project}:{m['id']}", "kind": kind, "id": m["id"], "project": project, "name": name,
            "title": str((st.nodes.get(m["id"]) or {}).get("title") or m.get("title") or ""),
            "open": int(m.get("open") or 0), "done": int(m.get("done") or 0), "items": int(m.get("items") or 0),
            "days": days, "part": part, "notes": _notes(m, undated)}


def _order(r: dict) -> tuple:
    """Dated first by median, then the dated parts by theirs, then the rows of no band."""
    return (0 if r["days"] and not r["part"] else 1 if r["days"] else 2, (r["days"] or {}).get("p50", 0), r["id"])


def _no_milestone(fc: dict, project: str, undated: list[dict]) -> dict:
    nm = fc.get("no_milestone") or {}
    days, part = _band(nm)
    loose = [u["id"] for u in undated if not u.get("milestone")]
    notes = [{"glyph": "⊘", "text": f"{'dated part only' if part else 'not dated'}: {_why(loose, undated)}"}] if (
        nm.get("shown") == "undated" and loose) else []
    return {"key": f"{project}:(no milestone)", "kind": "group", "id": "", "project": project,
            "name": "(no milestone)", "open": int(nm.get("open") or 0), "days": days, "part": part, "notes": notes}


def _backlog(fc: dict, project: str) -> dict:
    """The backlog's row: its flow while it grows faster than it empties (no band), else its range."""
    b, fl = fc.get("backlog") or {}, fc.get("flow") or {}
    row = {"key": f"{project}:(backlog)", "kind": "group", "id": "", "project": project, "name": "backlog",
           "open": int(b.get("open") or 0), "days": None, "part": False, "notes": []}
    if b.get("shown") == "growing":
        row["notes"].append({"glyph": "", "text": f"in {fl.get('created_per_day', 0):g}/day · out "
                                                   f"{fl.get('closed_per_day', 0):g}/day: does not empty at this rate"})
        return row
    row["days"], row["part"] = _band(b)
    if b.get("shown") == "undated":
        row["notes"].append({"glyph": "⊘", "text": f"dated part only: {b.get('undated', 0)} item(s) wait on gates"})
    elif fl.get("days"):
        row["notes"].append({"glyph": "", "text": "the inflow is not simulated"})
    return row


def collect(st, fc: dict | None, project: str, trees: dict | None = None) -> dict:
    """One project's bands: the heading, the forecast's day, its milestones' rows (the reached and dropped ones of
    the graph left out), « (no milestone) » and the backlog, and each row's item level (``levels``: a wave's lots
    from ``trees``, the Tree's, planviews.collect's). No forecast: no rows, the heading says how to get one."""
    out = {"project": project, "heading": heading(fc), "as_of": (fc or {}).get("as_of"), "rows": [], "tail": [],
           "levels": {}}
    if not fc:
        return out
    plan = waves.Plan(st.nodes)
    undated = (fc.get("gates") or {}).get("undated") or []
    rows = [_row(st, plan, m, project, undated) for m in fc.get("milestones") or []
            if (st.nodes.get(m.get("id")) or {}).get("status") not in ("reached", "dropped")]
    out["rows"] = sorted(rows, key=_order)
    out["tail"] = [r for r in (_no_milestone(fc, project, undated),) if r["open"]] + [_backlog(fc, project)]
    out["levels"] = levels(st, fc, project, trees, out["rows"])
    return out


# --- the chart: shared by the Textual view and the text twin ---

def cells(width: int) -> int:
    """The chart's cells at ``width`` columns."""
    return max(MIN_CELLS, width - NAME_W - OPEN_W - 4 - NOTE_W)


def default_scale(n: int) -> float:
    """The finest scale that shows the horizon and its ``▸`` cell in ``n`` cells."""
    return next((s for s in SCALES if (n - 1) * s >= _horizon()), SCALES[-1])


def zoom(scale: float, step: int) -> float:
    """The next scale: ``step`` -1 finer (``[``), +1 coarser (``]``), kept within ``SCALES``."""
    k = min(range(len(SCALES)), key=lambda i: abs(SCALES[i] - scale))
    return SCALES[max(0, min(len(SCALES) - 1, k + step))]


def last(scale: float) -> int:
    """The horizon's cell: the furthest offset ``chart`` still draws (its ``▸``)."""
    return math.ceil(_horizon() / scale)


def pan(offset: int, scale: float, step: int) -> int:
    """The offset ``step`` weeks later (+1, →) or earlier (-1, ←), never before the forecast's day nor past the
    horizon's cell."""
    return max(0, min(last(scale), offset + step * max(1, round(PAN_DAYS / scale))))


def rescaled(offset: int, old: float, new: float) -> int:
    """The offset that keeps the same first day at the new scale, never past the horizon's cell."""
    return max(0, min(last(new), round(offset * old / new)))


def _cell(a: float, b: float, d: dict) -> str:
    if a <= d["p50"] < b:
        return "median"
    if a < d["p80"] and b > d["p10"]:
        return "inner"
    if a < d["p90"] and b > d["p80"]:
        return "outer"
    return ""


def band(days: dict | None, n: int, scale: float, offset: int = 0, plain: bool = False) -> str:
    """A row's ``n`` cells: its band up to the horizon, ``▸`` in the first cell beyond it when the band goes on."""
    if not days:
        return " " * n
    marks = WORDS if plain else GLYPHS
    h, out = _horizon(), []
    for k in range(n):
        a = (offset + k) * scale
        if a >= h:
            first = k == 0 or a - scale < h
            out.append(marks["beyond"] if first and days["p90"] > h else " ")
            continue
        kind = _cell(a, a + scale, days)
        out.append(marks[kind] if kind else " ")
    return "".join(out)


def _as_of(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return None


def ticks(as_of: str | None, n: int, scale: float, offset: int = 0) -> str:
    """The dates over the chart: each Monday's day at its cell, a label left out where it would overlap."""
    now = _as_of(as_of)
    out = [" "] * n
    if now is None:
        return "".join(out)
    monday = now.date() + timedelta(days=(7 - now.date().weekday()) % 7 or 7)
    first = (datetime.combine(monday, datetime.min.time(), now.tzinfo) - now).total_seconds() / 86400
    free = 0
    for j in range(math.ceil((offset + n) * scale / 7) + 1):
        col = math.floor((first + 7 * j) / scale) - offset
        text = planviews._md((monday + timedelta(days=7 * j)).isoformat())
        if col >= free and col + len(text) <= n:
            out[col:col + len(text)] = text
            free = col + len(text) + 1
    return "".join(out)


def note_text(notes: list[dict], plain: bool = False) -> str:
    return " · ".join((n["text"] if plain or not n["glyph"] else f"{n['glyph']} {n['text']}") for n in notes)


def row_text(r: dict, n: int, scale: float, offset: int = 0, plain: bool = False, width: int | None = None) -> str:
    """One row: its name, its open items, its cells up to its band's last mark, then its notes (a row of no band in
    view, the backlog's flow: its notes right after its open items). Within ``width`` columns, notes too long for the
    room left wrap on lines under themselves (under the cells when that room is under ``WRAP_MIN``), never cut."""
    lead = "  ".join(x for x in (f"{r['name'][:NAME_W]:<{NAME_W}} {r['open']:>{OPEN_W}}",
                                 band(r["days"], n, scale, offset, plain).rstrip()) if x)
    notes = note_text(r["notes"], plain)
    if not notes:
        return lead
    if width is None or len(lead) + 2 + len(notes) <= width:
        return f"{lead}  {notes}"
    col = len(lead) + 2
    if width - col >= WRAP_MIN:
        first, *rest = textwrap.wrap(notes, width - col, break_on_hyphens=False)
        return "\n".join([f"{lead}  {first}", *(" " * col + x for x in rest)])
    col = NAME_W + 1 + OPEN_W + 2
    return "\n".join([lead, *(" " * col + x for x in textwrap.wrap(notes, width - col, break_on_hyphens=False))])


def legend(plain: bool = False) -> str:
    m = WORDS if plain else GLYPHS
    return (f"{m['inner']} p10–p80 · {m['outer']} p80–p90 · {m['median']} median · {m['beyond']} beyond "
            f"{forecast.HORIZON_DAYS // 7} weeks · [ ] scale · ←/→ pan · z or Enter its items")


def chart(group: dict, width: int, scale: float | None = None, offset: int = 0,
          plain: bool | None = None) -> tuple[str, list[tuple[dict, str]]]:
    """(the dates' row, [(row, its text: its notes wrapped on more lines)]) of one project's bands at ``width``
    columns."""
    plain = planviews.words() if plain is None else plain
    n = cells(width)
    scale = scale or default_scale(n)
    n = min(n, max(1, last(scale) + 1 - offset))   # nothing is drawn past the horizon's cell
    head = f"{'Milestone':<{NAME_W}} {'open':>{OPEN_W}}  {ticks(group.get('as_of'), n, scale, offset)}".rstrip()
    rows = [*(group.get("rows") or []), *(group.get("tail") or [])]
    return head, [(r, row_text(r, n, scale, offset, plain, width)) for r in rows]


def lines(panel: dict | None, width: int = planviews.WIDE, scale: float | None = None, offset: int = 0,
          plain: bool | None = None) -> list[str]:
    """The text twin: the heading, then each project's dates, rows and the legend."""
    plain = planviews.words() if plain is None else plain
    groups = (panel or {}).get("projects") or []
    out, drawn = ["Milestones · Trajectories"], False
    for g in groups:
        if "error" in g:
            out.append(f"  {g['project']}: error: {g['error']}")
            continue
        b = g.get("bands") or {}
        out.append(f"  {g['project']}: {b.get('heading', '')}" if len(groups) > 1 else f"  {b.get('heading', '')}")
        if not b.get("rows") and not b.get("tail"):
            continue
        head, rows = chart(b, width - 2, scale, offset, plain)
        out += [f"  {head}", *(f"  {x}" for _, t in rows for x in t.split("\n"))]
        drawn = True
    if not groups:
        out.append("  no project read yet")
    if drawn:
        out.append(f"  {legend(plain)}")
    return out


# --- the item level (wi-brain-tui-trajectories-items) ---

LABEL_W = 34         # an item's state, short id and priority
PAST_W = 10          # the past cells left of the « │ »
EST_W, CRIT_W = 9, 5
RIGHT_W = 1 + EST_W + 1 + CRIT_W + 2
PAST = {"glyph": "━", "word": "~"}
DONE_TICK = {"glyph": "✓", "word": "ok"}   # « ok Sep 13 », 9 cells: the day fits PAST_W
CHAIN = {"glyph": "◆", "word": "*"}
UNDATED = {"glyph": "┄", "word": "-"}
LEVEL_KINDS = ("milestone", "era", "wave")


def _short_item(nid: str, project: str) -> str:
    pre = f"wi-{project}-"
    return nid[len(pre):] if project and nid.startswith(pre) else nid


def _ids(nodes: list[dict]) -> list[str]:
    """The ids of the item nodes under ``nodes``, depth first, in their order."""
    out = []
    for n in nodes:
        if n.get("kind") == "item" and n.get("id"):
            out.append(n["id"])
        out += _ids(n.get("children") or [])
    return out


def _find(nodes: list[dict], key: str) -> dict | None:
    for n in nodes:
        if n.get("key") == key:
            return n
        hit = _find(n.get("children") or [], key)
        if hit:
            return hit
    return None


def _groups(st, row: dict, trees: dict) -> tuple[str, list[tuple[str, list[str]]]]:
    """(how the items are grouped, [(a group's name, its item ids)]): a pending wave's lots from the Tree's waves axis
    (brain.lots, the items in it now), then its other items; else every item through its sub-milestones, one group."""
    if row["kind"] == planviews.WAVE:
        node = _find(trees.get("waves") or [], row["key"])
        if node is not None:
            lots = [(c["name"], _ids(c["children"])) for c in node["children"] if c.get("kind") == "lot"]
            rest = _ids([c for c in node["children"] if c.get("kind") != "lot"])
            return ("lot" if lots else "order"), lots + ([("", rest)] if rest else [])
    return "order", [("", list(st.milestone_items(row["id"])))]


def _item_row(st, f: dict, nid: str, project: str, mid: str, past: dict, why: str | None, on_chain: bool) -> dict:
    n = st.nodes.get(nid) or {}
    props = n.get("props") or {}
    status = str(n.get("status") or "")
    prio = str(props.get("priority") or "") or (f"{props['priority_proposed']}?" if props.get("priority_proposed")
                                                 else "")
    done = str(props.get("done") or "")[:10] if status == "done" else ""
    return {"key": f"{project}:{nid}", "kind": "item", "id": nid, "project": project,
            "name": _short_item(nid, project), "title": str(n.get("title") or ""), "state": status, "priority": prio,
            "days": f.get("days"), "start": (f.get("start") or {}).get("days"), "hours": f.get("hours"),
            "critical": (f.get("critical") or {}).get(mid), "undated": why, "on_chain": on_chain,
            "past": {"first": past.get("first") or "", "done": done or past.get("done") or "",
                     "hours": past.get("hours")}}


class _Reads:
    """What a level reads of the forecast: its items, their order, why the others are not dated, the past."""

    def __init__(self, fc: dict) -> None:
        self.items = {i["id"]: i for i in fc.get("items") or [] if i.get("id")}
        self.rank = {i["id"]: k for k, i in enumerate(fc.get("items") or []) if i.get("id")}   # the scheduler's
        self.why = {u["id"]: u.get("why") or "" for u in (fc.get("gates") or {}).get("undated") or [] if u.get("id")}
        self.past = fc.get("past") or {}


def _group_rows(st, rd: _Reads, ids: list[str], row: dict, on: set[str], order: bool) -> tuple[list, list]:
    """(a group's open rows: the dated ones, in the scheduler's order when ``order``, then the others; its done
    rows), the dropped items left out."""
    dated, rest, done = [], [], []
    for nid in ids:
        status = (st.nodes.get(nid) or {}).get("status")
        if status == "dropped":
            continue
        r = _item_row(st, rd.items.get(nid) or {}, nid, row["project"], row["id"], rd.past.get(nid) or {},
                      rd.why.get(nid), nid in on)
        (done if status == "done" else dated if nid in rd.items else rest).append(r)
    if order:
        dated.sort(key=lambda r: (rd.rank.get(r["id"], math.inf), r["id"]))
    rest.sort(key=lambda r: (r["undated"] is None, r["id"]))
    return dated + rest, done


def _level(st, fc: dict, row: dict, trees: dict) -> dict:
    """One row's item level: its groups' rows (a group's name, then its items), its done items last."""
    project, mid = row["project"], row["id"]
    rd = _Reads(fc)
    chain = next((m for m in fc.get("milestones") or [] if m.get("id") == mid), {}).get("chain")
    on = set((chain or {}).get("items") or ())
    by, groups = _groups(st, row, trees)
    rows, done = [], []
    for name, ids in groups:
        open_, closed = _group_rows(st, rd, ids, row, on, by == "order")
        done += closed
        if open_ and name:
            rows.append({"key": f"{row['key']}:{name}", "kind": "group", "name": name})
        rows += open_
    if done:
        done.sort(key=lambda r: (r["past"]["done"], r["id"]), reverse=True)
        rows.append({"key": f"{row['key']}:done", "kind": "group", "name": f"✓ {len(done)} done"})
        rows += done
    return {"key": row["key"], "id": mid, "project": project, "name": row["name"], "kind": row["kind"],
            "title": row.get("title", ""), "done": row.get("done", 0), "items": row.get("items", 0), "by": by,
            "chain": chain, "chain_text": forecast.chain_text(chain, project, fc), "rows": rows}


def levels(st, fc: dict | None, project: str, trees: dict | None, rows: list[dict]) -> dict[str, dict]:
    """{a banded row's key: its item level}, for each milestone, era and wave of ``rows`` (``collect``'s)."""
    if not fc:
        return {}
    return {r["key"]: _level(st, fc, r, trees or {}) for r in rows if r["kind"] in LEVEL_KINDS}


def level_heading(lv: dict, fc_heading: str) -> str:
    grouped = "grouped by lot" if lv["by"] == "lot" else "in the scheduler's order"
    return f"{lv['project']} › {lv['name']} › items · {grouped} · {fc_heading}"


def _day(text: str):
    try:
        return datetime.fromisoformat(str(text)[:10]).date()
    except ValueError:
        return None


def _item_cell(a: float, b: float, d: dict, s: dict | None) -> str:
    """A future cell of an item: its finish's median, its start-to-finish core, its tails; a forecast with no start:
    its finish band alone (``_cell``)."""
    if not s:
        return _cell(a, b, d)
    if a <= d["p50"] < b:
        return "median"
    if a < d["p80"] and b > s["p50"]:
        return "inner"
    if (a < s["p50"] and b > s["p10"]) or (a < d["p90"] and b > d["p80"]):
        return "outer"
    return ""


def item_band(r: dict, n: int, scale: float, offset: int = 0, plain: bool = False) -> str:
    """An item's ``n`` future cells: its start-to-finish band, ``▸`` past the horizon; « ┄┄ undated: why » when the
    forecast cannot date it."""
    days = r.get("days")
    if not days:
        if r.get("undated") is not None and r.get("state") != "done":
            text = f"{UNDATED['word' if plain else 'glyph'] * 2} undated: {forecast.gate_kind(r['undated'])}"
            return text[:n].ljust(n)
        return " " * n
    marks = WORDS if plain else GLYPHS
    h, out = _horizon(), []
    for k in range(n):
        a = (offset + k) * scale
        if a >= h:
            first = k == 0 or a - scale < h
            out.append(marks["beyond"] if first and days["p90"] > h else " ")
            continue
        kind = _item_cell(a, a + scale, days, r.get("start"))
        out.append(marks[kind] if kind else " ")
    return "".join(out)


def past_cells(r: dict, as_of: str | None, scale: float, plain: bool = False) -> str:
    """The ``PAST_W`` cells before the forecast's day: the item's actual bar from its first session to its done day
    (to the forecast's day while it is doing), « ✓ <day> » when it ended before the window."""
    now = _as_of(as_of)
    first, end, done = _span(r, now.date() if now else None)
    if now is None or not (first or done):
        return " " * PAST_W
    tick = f"{DONE_TICK['word' if plain else 'glyph']} {planviews._md(done.isoformat())}" if done else ""
    if first is None or end is None:
        return tick.rjust(PAST_W)[:PAST_W]
    lo, hi = (first - now.date()).days, (end - now.date()).days + 1   # days from the forecast's day, [lo, hi)
    if hi <= -PAST_W * scale:
        return tick.rjust(PAST_W)[:PAST_W]
    mark = PAST["word" if plain else "glyph"]
    return "".join(mark if (j - PAST_W) * scale < hi and (j - PAST_W + 1) * scale > lo else " "
                   for j in range(PAST_W))


def _span(r: dict, today):
    """(its first session's day, the end of its bar: its done day, or ``today`` while doing; its done day)."""
    p = r.get("past") or {}
    first, done = _day(p.get("first") or ""), _day(p.get("done") or "")
    return first, done or (today if r.get("state") == "doing" else None), done


def _est(r: dict) -> str:
    if r.get("state") == "done":
        h = (r.get("past") or {}).get("hours")
        return f"{h:.1f} act" if h is not None else "-"
    q = r.get("hours")
    return f"{q['p10']:.1f}–{q['p90']:.1f}" if q else "-"


def _crit(r: dict) -> str:
    return f"{r['critical']:.0%}" if r.get("critical") is not None and r.get("state") != "done" else "-"


def item_cells(width: int) -> int:
    """The item level's future cells at ``width`` columns."""
    return max(MIN_CELLS, width - LABEL_W - 1 - PAST_W - 1 - RIGHT_W)


def item_text(r: dict, n: int, scale: float, offset: int, as_of: str | None, plain: bool, chain: bool) -> str:
    """One row of the item level: a group's name alone, or an item's label, past, future and columns."""
    if r["kind"] == "group":
        return r["name"].replace("✓", "done:") if plain else r["name"]
    state = r["state"][:5] if plain else planviews.STATES.get(r["state"], "?")
    label = f"{state} {r['name']} {r['priority'] or '-'}"
    if len(label) > LABEL_W:
        label = label[:LABEL_W - 1] + "…"
    mark = CHAIN["word" if plain else "glyph"] if chain and r.get("on_chain") else " "
    return (f"{label:<{LABEL_W}} {past_cells(r, as_of, scale, plain)}{'|' if plain else '│'}"
            f"{item_band(r, n, scale, offset, plain)} {_est(r):>{EST_W}} {_crit(r):>{CRIT_W}} {mark}").rstrip()


def item_legend(plain: bool = False, chain: bool = True) -> str:
    m, p, c = (WORDS, PAST["word"], CHAIN["word"]) if plain else (GLYPHS, PAST["glyph"], CHAIN["glyph"])
    return (f"{p} past · {m['outer']} start p10–p50, end p80–p90 · {m['inner']} start p50 to end p80 · {m['median']} "
            f"end median · {c} critical chain{'' if chain else ': c'} · crit. its index · Z or Escape back")


def item_chart(lv: dict, as_of: str | None, width: int, scale: float | None = None, offset: int = 0,
               plain: bool | None = None, chain: bool = True) -> tuple[list[str], list[tuple[dict, str]]]:
    """(the head lines: the chain's line when ``chain``, the dates' row; [(row, its text)]) of one item level at
    ``width`` columns."""
    plain = planviews.words() if plain is None else plain
    n = item_cells(width)
    scale = scale or default_scale(n)
    n = min(n, max(1, last(scale) + 1 - offset))   # nothing is drawn past the horizon's cell
    head = [f"critical (most futures): {lv['chain_text']}"] if chain and lv.get("chain_text") else []
    head.append(f"{'item':<{LABEL_W}} {'past':>{PAST_W}}{'|' if plain else '│'}{ticks(as_of, n, scale, offset)} "
                f"{'est. h':>{EST_W}} {'crit.':>{CRIT_W}}")
    return head, [(r, item_text(r, n, scale, offset, as_of, plain, chain)) for r in lv.get("rows") or []]


def find_level(bands: dict, project: str, ref: str) -> dict | None:
    """A project's level of ``ref``: a row's key, a milestone's id, its name in the chart or its short id."""
    lvs = bands.get("levels") or {}
    named = [k for k, lv in lvs.items() if ref in (lv["name"], lv["id"])]
    for key in (ref, f"{project}:{ref}", *named, *(f"{project}:{pre}{ref}" for pre in (f"ms-{project}-", "ms-"))):
        if key in lvs:
            return lvs[key]
    return None


def zoom_lines(panel: dict | None, ref: str, width: int = planviews.WIDE, plain: bool | None = None) -> list[str]:
    """The text twin of the item level (``brain tui --once --tab milestones --view trajectories --zoom
    <milestone>``): each project's level of ``ref``, the chain marked."""
    plain = planviews.words() if plain is None else plain
    out, found = ["Milestones · Trajectories · items"], False
    for g in (panel or {}).get("projects") or []:
        b = g.get("bands") or {}
        lv = find_level(b, g["project"], ref)
        if lv is None:
            continue
        found = True
        out.append(f"  {level_heading(lv, b.get('heading', ''))}")
        head, rows = item_chart(lv, b.get("as_of"), width - 2, None, 0, plain, chain=True)
        out += [f"  {x}" for x in head] + [f"  {t}" for _, t in rows]
        out.append(f"  {item_legend(plain)}")
    if not found:
        out.append(f"  {ref}: no milestone, era or wave of that id in the forecast's rows (brain forecast)")
    return out
