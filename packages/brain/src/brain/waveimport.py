"""``brain wave import`` (wi-brain-waves-as-releases): a wave per release the items' free-text ``props.wave`` names,
proposed (or, with ``--write``, created, its release pinned) with the items' part_of edges; ``props.wave`` is kept as
the record of when each item was planned. A value that names no release is listed for the owner to place. Moved out
of brain.waves (wi-brain-wave-ids-decoupled), which keeps the plan, the checks and the close.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import graph
from .waves import RELEASE_IN_RE, Plan, WaveError, _props, add, load, release_key


@dataclass(frozen=True)
class Import:
    waves: dict[str, list[str]]       # release -> the items whose props.wave names it, not yet in a wave
    existing: dict[str, str]          # release -> the wave that holds it already
    to_place: dict[str, list[str]]    # a props.wave that names no release -> its items
    before: dict[str, list[str]] = field(default_factory=dict)   # release before ``start`` -> its items, left as is


def plan_import(store: Path, start: str = "") -> Import:
    """The waves the items' props.wave names; ``start`` (X.Y.Z): the releases before it, already tagged, are listed
    and left out, so that no past release becomes a pending wave that brain next would name."""
    if start and release_key(start) is None:
        raise WaveError(f"--from {start}: a release X.Y.Z (the first release to import)")
    plan = load(store)
    waves, to_place = _wave_values(plan)
    order = sorted(waves, key=lambda r: release_key(r) or (0, 0, 0))
    floor = release_key(start) or (0, 0, 0)
    kept = [r for r in order if (release_key(r) or (0, 0, 0)) >= floor]
    return Import({r: waves[r] for r in kept}, {r: plan.resolve(r) for r in kept if plan.resolve(r)},
                  dict(sorted(to_place.items())), {r: waves[r] for r in order if r not in kept})


def _wave_values(plan: Plan) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """The items in no wave by their free-text props.wave: (the release it names -> its items, any other value -> its
    items)."""
    waves: dict[str, list[str]] = defaultdict(list)
    to_place: dict[str, list[str]] = defaultdict(list)
    for k in sorted(k for k in plan.nodes if plan.is_item(k)):
        raw = _props(plan.nodes[k]).get("wave")
        if raw in (None, "") or plan.planned(k):
            continue
        m = RELEASE_IN_RE.match(str(raw))
        if m:
            waves[m.group(1)].append(k)
        else:
            to_place[" ".join(str(raw).split())].append(k)
    return waves, to_place


def do_import(store: Path, *, write: bool = False, today: str | None = None, start: str = "") -> Import:
    """Propose (``write``: create) a wave per release the items' free-text props.wave names, from ``start`` on, and
    their part_of edges; props.wave is kept as the record of when it was planned."""
    imp = plan_import(store, start)
    if not write:
        return imp
    day = today or date.today().isoformat()
    for rel, items in imp.waves.items():
        wid = imp.existing.get(rel)
        if not wid:
            wid = add(store, rel, today=day, pin=True,
                      decided=f"brain wave import, {day}, from the items' props.wave")["id"]
        graph.append_edges(store, [{"from": i, "to": wid, "type": "part_of"} for i in items], "edges/work.yaml",
                           f"{day}: brain wave import ({rel})")
    return imp
