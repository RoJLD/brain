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


def collect(st, fc: dict | None, project: str) -> dict:
    """One project's bands: the heading, the forecast's day, its milestones' rows (the reached and dropped ones of
    the graph left out), « (no milestone) » and the backlog. No forecast: no rows, the heading says how to get one."""
    out = {"project": project, "heading": heading(fc), "as_of": (fc or {}).get("as_of"), "rows": [], "tail": []}
    if not fc:
        return out
    plan = waves.Plan(st.nodes)
    undated = (fc.get("gates") or {}).get("undated") or []
    rows = [_row(st, plan, m, project, undated) for m in fc.get("milestones") or []
            if (st.nodes.get(m.get("id")) or {}).get("status") not in ("reached", "dropped")]
    out["rows"] = sorted(rows, key=_order)
    out["tail"] = [r for r in (_no_milestone(fc, project, undated),) if r["open"]] + [_backlog(fc, project)]
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
            f"{forecast.HORIZON_DAYS // 7} weeks · [ ] scale · ←/→ pan · Enter detail")


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
