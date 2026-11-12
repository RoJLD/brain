"""Item sizes (wi-brain-item-size): every item carries ``props.size`` (S, M, L, XL) and ``props.size_reason`` (one
line), the judgement of the session that writes it (``brain item add --size``, ``brain item set``). A script cannot
guess a size (the free signals predict the cost poorly), so the engine only checks that one is given, and measures
how wrong it was against the actuals (wi-brain-size-calibration, brain.cost): ``brain cost review`` says each
finished item's judged size against the size its active time falls in on this scale, ``brain cost audit`` the misses
per size and class and the thresholds the history proposes, and ``brain cost estimate`` takes the size as its first
similarity key only while that lowers the backtests' error.

The scale, until the recalibration moves it: S under about 0.3 h of active time, M up to about 0.8 h, L up to about
2 h, XL beyond (to be split when possible). ``HOURS`` is the ordinal-to-number conversion the ranking reads (a
written setting, not a hidden constant).

``brain check`` warns on an open item written by ``brain item add`` since the rule (it stamps ``props.created``)
without a size, on an open item whose size is off the scale, and on one with a size but no reason. The proposals
the engine writes itself (a lesson's prevention item, an audit's debt item) carry no stamp: the session that adopts
one sizes it. The items written before the rule carry no
``created`` stamp: they are sized once, in batches, by a session that reads each one.
"""

from __future__ import annotations

import statistics
from pathlib import Path

from . import graph, usage

SIZES = graph.SIZES
HOURS = {"S": 0.3, "M": 0.8, "L": 2.0, "XL": 4.0}   # active hours of each size: the scale's upper bounds, XL twice L
VERDICTS = ("hit", "under", "over")   # a judged size against the actual
MIN_ITEMS = 3   # items judged a size before a threshold is proposed (brain.cost.MIN_SIMILAR's value)
OPEN = ("todo", "doing", "blocked")   # a closed status of any schema (done, dropped, superseded...) is not open
LIST_MAX = 10


def open_items(store: Path) -> list[dict]:
    """The store's open WorkItems (curated files only)."""
    return [n for _, n in graph.node_index(store, generated=False).values()
            if n.get("type") == "WorkItem" and n.get("status") in OPEN]


def unsized(store: Path) -> list[str]:
    """The ids of the open items written since the rule (props.created) that carry no size."""
    return sorted(n["id"] for n in open_items(store)
                  if (n.get("props") or {}).get("created") and not (n.get("props") or {}).get("size"))


def off_scale(store: Path) -> list[str]:
    """The ids of the open items whose size is not one of SIZES (a hand edit: m, medium, 2)."""
    return sorted(n["id"] for n in open_items(store)
                  if (n.get("props") or {}).get("size") and (n.get("props") or {}).get("size") not in SIZES)


def unreasoned(store: Path) -> list[str]:
    """The ids of the open items with a size and no size_reason."""
    return sorted(n["id"] for n in open_items(store)
                  if (n.get("props") or {}).get("size") and not (n.get("props") or {}).get("size_reason"))


def _ids(ids: list[str]) -> str:
    more = f" and {len(ids) - LIST_MAX} more" if len(ids) > LIST_MAX else ""
    return ", ".join(ids[:LIST_MAX]) + more


def check_lines(store: Path) -> list[str]:
    """``brain check``'s warnings about the sizes; nothing when every item that needs one has it."""
    lines = []
    bare = unsized(store)
    if bare:
        lines.append(f"warning: {len(bare)} open item(s) written without a size (brain item set ID size=S|M|L|XL "
                     f"size_reason=...): {_ids(bare)}")
    off = off_scale(store)
    if off:
        lines.append(f"warning: {len(off)} open item(s) with a size off the scale {', '.join(SIZES)} (brain item set ID "
                     f"size=...): {_ids(off)}")
    why = unreasoned(store)
    if why:
        lines.append(f"warning: {len(why)} open item(s) with a size and no size_reason (brain item set ID "
                     f"size_reason=...): {_ids(why)}")
    return lines


def hours(node: dict) -> float | None:
    """The active hours the item's size stands for, None without a size."""
    return HOURS.get(str((node.get("props") or {}).get("size") or ""))


# --- the sizes against the actuals (wi-brain-size-calibration; brain cost review and audit) ---

def size_of(hours: float) -> str:
    """The size an active time falls in on the scale (brain.HOURS: each size's upper bound; XL beyond L)."""
    return next((s for s in SIZES[:-1] if hours <= HOURS[s]), SIZES[-1])


def size_check(a: dict) -> dict | None:
    """An item's judged size against its actual: {judged, actual, hours, verdict: hit, under (the work was bigger
    than judged) or over}; None without a judged size."""
    if not a.get("size"):
        return None
    hours = (a.get("active_s") or 0) / 3600
    got = size_of(hours)
    order = SIZES.index
    verdict = "hit" if got == a["size"] else "under" if order(got) > order(a["size"]) else "over"
    return {"judged": a["size"], "actual": got, "hours": round(hours, 2), "verdict": verdict}


def sizes(items: list[dict], everything: list[dict]) -> dict:
    """The sizes against the actuals: ``items`` (the window's finished items) each checked and grouped by size and
    class (n, hits, under, over, median hours and cost), and the thresholds ``everything`` (the whole history)
    proposes: each size's p75 of active hours among the items judged that size (MIN_ITEMS at least), beside the
    scale's."""
    rows = [dict(c, id=a["id"], cls=a["class"], cost=a["cost"]) for a in items for c in [size_check(a)] if c]
    return {"items": rows, "table": _size_table(rows), "thresholds": _thresholds(everything),
            "misses": sum(r["verdict"] != "hit" for r in rows)}


def _size_table(rows: list[dict]) -> list[dict]:
    """The checked items grouped by judged size and class: n, hits, under, over, median hours and cost."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["judged"], r["cls"]), []).append(r)
    order = SIZES.index
    return [{"size": s, "class": c, "n": len(g), **{v: sum(r["verdict"] == v for r in g) for v in VERDICTS},
             "hours": round(statistics.median(r["hours"] for r in g), 2),
             "cost": round(statistics.median(r["cost"] for r in g), 2)}
            for (s, c), g in sorted(groups.items(), key=lambda kv: (order(kv[0][0]), kv[0][1]))]


def _thresholds(everything: list[dict]) -> list[dict]:
    """Each size's upper bound now and the one the history proposes: the p75 of the active hours of the items
    judged that size (MIN_ITEMS at least, else None)."""
    checked = [x for x in (size_check(a) for a in everything) if x]
    out = []
    for s in SIZES[:-1]:
        hours = [x["hours"] for x in checked if x["judged"] == s]
        q = usage.quantiles(hours) if len(hours) >= MIN_ITEMS else {"n": 0}
        out.append({"size": s, "now": HOURS[s], "n": len(hours),
                    "proposed": round(q["p75"], 2) if q["n"] else None})
    return out


def render_sizes(sz: dict | None, key: dict | None) -> list[str]:
    """The audit's « Sizes against actuals » (wi-brain-size-calibration)."""
    lines = ["", "## Sizes against actuals (props.size against the active time)", ""]
    if not sz or not sz["items"]:
        return lines + ["- no finished item of the window carries a size"]
    lines.append(f"{len(sz['items'])} sized item(s), {sz['misses']} miss(es) (the scale: "
                 + ", ".join(f"{s} up to {h} h" for s, h in HOURS.items() if s != SIZES[-1])
                 + f", {SIZES[-1]} beyond).")
    lines += [f"- {r['size']} {r['class'] or 'no class'}: {r['n']} item(s), {r['hit']} hit, {r['under']} under-sized, "
              f"{r['over']} over-sized; median {r['hours']} h, {usage.usd(r['cost'])}" for r in sz["table"]]
    lines += [f"  - {r['id']}: {r['judged']} judged, {r['hours']} h is {r['actual']}" for r in sz["items"]
              if r["verdict"] != "hit"]
    return lines + _threshold_lines(sz["thresholds"], key)


def _threshold(t: dict) -> str:
    if t["proposed"] is None:
        return f"- {t['size']}: now {t['now']} h, proposed - ({t['n']} item(s), {MIN_ITEMS} needed)"
    return f"- {t['size']}: now {t['now']} h, proposed {t['proposed']} h ({t['n']} item(s))"


def _threshold_lines(thresholds: list[dict], key: dict | None) -> list[str]:
    """The thresholds the history proposes, whether they rise with the size, and the size key's verdict."""
    lines = ["", "Thresholds proposed (each size's p75 of active hours among the items judged it, whole history):"]
    lines += [_threshold(t) for t in thresholds]
    got = [t["proposed"] for t in thresholds if t["proposed"] is not None]
    if any(b <= a for a, b in zip(got, got[1:])):
        lines.append("- the proposals do not rise with the size: the judged sizes do not separate the active time "
                     "yet (judge again from the misses above before moving the scale)")
    if key and key.get("with") is not None:
        lines.append(f"- the size as the estimator's first key: {'kept' if key['kept'] else 'left out'} (backtests' "
                     f"error x{key['with']} with it, x{key['without']} without)")
    return lines
