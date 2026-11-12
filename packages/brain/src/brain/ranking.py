"""The rank of the work frontier (wi-brain-prioritization), at zero token: the owner's priority first (a confirmed
one before the same one proposed), then the owner's explicit order (``props.order``, lower first), then WSJF, value
over effort, then the id. ``brain next`` lists each wave's items in this order, its quick wins first, and ``--explain``
shows each score's parts; the cockpit's frontier sorts by it and shows the size, the value and the score.

- **Value**, derived by default from the graph (COST-5's default score, ``SCORE``): a base, plus the value of the
  features the item delivers (``delivers`` edges to Feature nodes and their ``props.value``), plus a milestone it moves
  (``part_of`` a milestone of the roadmap: a wave or an era is a timebox, not a milestone moved), plus half a point
  for each open item that depends on it. The owner overrides it on an item with ``props.value`` (high, medium, low)
  and ``props.value_reason``; the override wins, is marked and counted (if it is frequent, the weights are wrong).
- **Effort**, the active hours the item's size stands for (``brain.sizing.HOURS``); an item without a size counts as
  ``DEFAULT_SIZE`` and is marked so.
- **Quick wins**: open items of size S whose value is high (an override ``high``, or a derived value at or above
  ``HIGH``).

Every number here is a written setting, not a hidden constant (spec-brain-psychohistory 4.3); ``brain forecast``
breaks its ties with the same ``SCORE``.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from . import sizing

# COST-5's default score: value = base + the value of the features delivered + a milestone moved + 0.5 per open
# item unblocked (brain forecast's tie-breaker too).
SCORE = {"base": 1.0, "feature": {"high": 3.0, "medium": 2.0, "low": 1.0}, "milestone": 1.0, "unblocks": 0.5}
VALUE = {"high": 5.0, "medium": 3.0, "low": 1.0}   # an owner's props.value on the derived scale
HIGH = 4.0            # a derived value at or above reads high (a high feature and a milestone moved)
MEDIUM = 2.5          # at or above reads medium, below low
DEFAULT_SIZE = "M"    # the effort of an item without a size
PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
OPEN = ("todo", "doing", "blocked")
TIMEBOXES = ("wave", "era")   # milestone kinds that do not count as a milestone moved


@dataclass(frozen=True)
class Score:
    id: str
    value: float
    parts: dict = field(default_factory=dict)   # base, features, milestone, unblocks (the derivation)
    override: str = ""    # props.value when the owner set one
    size: str = ""        # props.size, "" when none (the effort is DEFAULT_SIZE's)
    hours: float = 0.0
    score: float = 0.0

    @property
    def level(self) -> str:
        """high, medium or low: the override, else the derived value against HIGH and MEDIUM."""
        if self.override:
            return self.override
        return "high" if self.value >= HIGH else "medium" if self.value >= MEDIUM else "low"

    @property
    def quick_win(self) -> bool:
        return self.size == "S" and self.level == "high"

    def as_dict(self) -> dict:
        return {"value": self.value, "level": self.level, "parts": dict(self.parts), "override": self.override,
                "size": self.size, "hours": self.hours, "score": self.score, "quick_win": self.quick_win,
                "explain": self.explain()}

    def explain(self) -> str:
        """``score 12.5 = value 3.75 / 0.3 h (S)``, the value's parts or its override."""
        if self.override:
            why = f"{self.override}, the owner's (derived {_g(sum(self.parts.values()))})"
        else:
            why = " + ".join(f"{k} {_g(v)}" for k, v in self.parts.items() if v or k == "base")
        size = self.size or f"{DEFAULT_SIZE}?, no size"
        return f"score {_g(self.score)} = value {_g(self.value)} ({why}) / {_g(self.hours)} h ({size})"


def _g(x: float) -> str:
    return f"{round(x, 2):g}"


class Ranker:
    """The scores of a store's open items, from its nodes ({id: node}) and edges (dicts with from, to, type)."""

    def __init__(self, nodes: dict, edges) -> None:
        self.nodes = nodes
        self.features: dict[str, list[str]] = {}
        self.moves: dict[str, list[str]] = {}
        dependents: Counter = Counter()
        for e in edges:
            src, dst, etype = str(e.get("from")), str(e.get("to")), e.get("type")
            target = nodes.get(dst) or {}
            if etype == "delivers" and target.get("type") == "Feature":
                self.features.setdefault(src, []).append(dst)
            elif etype == "part_of" and target.get("type") == "Milestone" \
                    and str(_props(target).get("kind") or "") not in TIMEBOXES:
                self.moves.setdefault(src, []).append(dst)
            elif etype in ("depends_on", "gated_by") and (nodes.get(src) or {}).get("status") in OPEN:
                dependents[dst] += 1
        self.dependents = dependents
        self._memo: dict[str, Score] = {}

    def score(self, nid: str) -> Score:
        if nid not in self._memo:
            self._memo[nid] = self._score(nid)
        return self._memo[nid]

    def _score(self, nid: str) -> Score:
        node = self.nodes.get(nid) or {}
        p = _props(node)
        parts = {"base": SCORE["base"],
                 "features": sum(SCORE["feature"].get(str(_props(self.nodes[f]).get("value") or ""), 0.0)
                                 for f in self.features.get(nid, ())),
                 "milestone": SCORE["milestone"] if self.moves.get(nid) else 0.0,
                 "unblocks": SCORE["unblocks"] * self.dependents.get(nid, 0)}
        override = str(p.get("value") or "").lower()   # an item's; a Feature's value is its own, not an override
        override = override if override in VALUE and node.get("type") == "WorkItem" else ""
        value = VALUE[override] if override else sum(parts.values())
        size = str(p.get("size") or "").upper()
        size = size if size in sizing.SIZES else ""
        hours = sizing.HOURS[size or DEFAULT_SIZE]
        return Score(nid, round(value, 4), parts, override, size, hours, round(value / hours, 4))

    def key(self, nid: str) -> tuple:
        """The rank: priority (confirmed before proposed, none last), the owner's order, the score (highest first),
        the id."""
        p = _props(self.nodes.get(nid) or {})
        pri, proposed = str(p.get("priority") or ""), False
        if pri not in PRIORITY:
            pri, proposed = str(p.get("priority_proposed") or "").rstrip("?"), True
        order = order_of(self.nodes.get(nid) or {})
        return PRIORITY.get(pri, 9), proposed, math.inf if order is None else order, -self.score(nid).score, nid

    def ranked(self, ids) -> list[str]:
        return sorted(ids, key=self.key)

    def overrides(self, ids) -> list[str]:
        """The items among ``ids`` whose value the owner set (COST-5's revisit counts them)."""
        return [i for i in ids if self.score(i).override]


def order_of(node: dict) -> float | None:
    """The owner's explicit order (props.order, a number: lower first), None when there is none or it is text."""
    order = _props(node).get("order")
    return order if isinstance(order, (int, float)) and not isinstance(order, bool) else None


def _props(node: dict) -> dict:
    p = node.get("props")
    return p if isinstance(p, dict) else {}
