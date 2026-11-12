"""Item sizes (wi-brain-item-size): every item carries ``props.size`` (S, M, L, XL) and ``props.size_reason`` (one
line), the judgement of the session that writes it (``brain item add --size``, ``brain item set``). A script cannot
guess a size (the free signals predict the cost poorly), so the engine only checks that one is given, and later
measures how wrong it was against the actuals (wi-brain-size-calibration).

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

from pathlib import Path

from . import graph

SIZES = graph.SIZES
HOURS = {"S": 0.3, "M": 0.8, "L": 2.0, "XL": 4.0}   # active hours of each size: the scale's upper bounds, XL twice L
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
