"""``brain wave close`` (wi-brain-waves-as-releases, wi-brain-wave-ids-decoupled): the closure a version PR makes. The
wave of a release (or the current wave, when the release jumped to the next minor or major) is reached with
``props.shipped_as``; each of its open items is carried by name to a later wave (``props.carried_to``) or dropped. A
``--carry-to`` is read against the plan once the wave is closed (:func:`brain.waves._after`), so after a jump the
later waves' computed releases are the ones it names; a release with no wave yet creates the next ``wave-sN``, last,
its release pinned only when it is not the computed one. Moved out of brain.waves, which keeps the plan and its checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import graph
from .waves import OPEN, Plan, WaveError, _after, add, ambiguous, load, next_release, release_key


@dataclass(frozen=True)
class Closing:
    wave: str
    release: str
    carry_to: str          # the wave id the carried items go to, '' when none
    carried: list[str]
    dropped: list[str]
    left: list[str]        # open items neither carried nor dropped: the wave cannot close
    done: int
    created: bool = False  # the carry-to wave does not exist yet: closing creates it beside the closed one
    shipped_as: str = ""   # the version the wave ships as (props.shipped_as): the version closed
    carry_release: str = ""   # the release --carry-to named, when closing creates its wave
    carry_label: str = ""     # the release of the wave carried to, once the wave is closed
    carry_pin: bool = False   # the created wave pins its release (it is not the computed one)


def _wave_to_close(plan: Plan, version: str) -> str:
    amb = ambiguous(plan, version)
    if amb:
        raise WaveError(amb)
    w = plan.for_release(version)
    if w is None:
        raise WaveError(f"{version}: no wave of that release, and not the next minor or major after the current "
                        f"wave's (brain next)")
    if plan.status(w) != "pending":
        raise WaveError(f"{w}: already {plan.status(w)}")
    return w


def _carry_target(after: Plan, w: str, carry_to: str) -> str:
    """The later wave ``carry_to`` names in ``after`` (the plan once ``w`` is closed: :func:`_after`), '' when none is
    given; a release with no wave yet names the wave that closing creates (the next ``wave-sN``, beside the closed
    one: the owner, 2026-11-10; its release computed, or pinned when it is not the computed one)."""
    if not carry_to:
        return ""
    target = after.resolve(carry_to)
    if not target:
        key = release_key(carry_to)
        if key is None:
            raise WaveError(f"--carry-to {carry_to}: no wave of that name, and not a release X.Y.Z to create")
        if key <= (release_key(after.shipped(w)) or (0, 0, 0)):
            raise WaveError(f"--carry-to {carry_to}: not after {after.shipped(w)}")
        last = release_key(next_release(after)) or (0, 0, 0)
        if key < last:   # a created wave goes last: its release after every other one's
            raise WaveError(f"--carry-to {carry_to}: no live wave of that release, and a new wave goes last, from "
                            f"{next_release(after)} on (carry to a wave by its id or its release)")
        return f"wave-s{after.next_seq()}"
    if after.waves.index(target) <= after.waves.index(w):
        raise WaveError(f"--carry-to {carry_to}: not after {after.shipped(w)}")
    if after.status(target) != "pending":
        raise WaveError(f"--carry-to {carry_to}: {target} is {after.status(target) or 'without a status'}, not "
                        "pending (an item carried there would be in no live wave)")
    return target


def plan_close(plan: Plan, version: str, carry_to: str = "", drop: list[str] | None = None) -> Closing:
    """What closing the wave ``version`` does: its open items carried to ``carry_to`` (read against the plan once the
    wave is closed: a jump's later waves have moved), those of ``drop`` dropped."""
    w = _wave_to_close(plan, version)
    shipped = _shipped_as(plan, w, version)
    after = _after(plan, w, shipped)
    target = _carry_target(after, w, carry_to)
    items = plan.items_of(w)
    drop = _drops(plan, w, items, drop)
    rest = [i for i in items if plan.status(i) in OPEN and i not in drop]
    done = sum(1 for i in items if plan.status(i) == "done")
    created = bool(target) and target not in plan.nodes
    return Closing(w, plan.label(w), target, rest if target else [], drop, [] if target else rest, done,
                   created=created, shipped_as=shipped, carry_release=carry_to if created else "",
                   carry_label=(carry_to if created else after.label(target)) if target else "",
                   carry_pin=created and carry_to != next_release(after))


def _drops(plan: Plan, w: str, items: list[str], drop: list[str] | None) -> list[str]:
    """``drop`` once each; :class:`WaveError` for one that is not an open item of ``w``."""
    drop = list(dict.fromkeys(drop or []))
    unknown = [d for d in drop if d not in items or plan.status(d) not in OPEN]
    if unknown:
        raise WaveError(f"--drop {', '.join(unknown)}: not an open item of {w}")
    return drop


def _shipped_as(plan: Plan, w: str, version: str) -> str:
    """The version a wave closes as: the release given, else its label (closed by its id)."""
    return version if release_key(version) else plan.label(w)


def close(store: Path, version: str, carry_to: str = "", drop: list[str] | None = None, *, write: bool = False,
          today: str | None = None, root: Path | None = None) -> Closing:
    """The closure of a wave: its open items carried to ``carry_to`` (props.carried_to) or dropped, then the wave
    reached with what it did. Writes only with ``write`` and when nothing is left."""
    plan = load(store, root)
    c = plan_close(plan, version, carry_to, drop)
    if not write or c.left:
        return c
    day = today or date.today().isoformat()
    if c.created:   # the next wave, part of what the closed wave is part of; its release computed (after the close),
        parents = plan.parents.get(c.wave) or []   # unless --carry-to named another one (then pinned: props.release)
        add(store, c.carry_release if c.carry_pin else "", parent=parents[0] if parents else "", today=day,
            pin=c.carry_pin, decided=f"created by brain wave close {c.shipped_as} --carry-to {c.carry_release}")
    for i in c.dropped:
        graph.close_item(store, i, "", f"at the close of wave {c.release}", today=day, status="dropped")
    for i in c.carried:   # carried again: the wave it leaves joins the ones it went through
        via = plan.via(i) + [c.wave] if plan.carried_in(i) else []
        graph.set_item(store, i, [f"props.carried_to={c.carry_to}"] + ([f"props.carried_via={', '.join(via)}"]
                                                                        if via else []))
    to = f", {len(c.carried)} carried to {c.carry_label}" if c.carried else ""
    graph.set_item(store, c.wave, ["status=reached", f"props.shipped_as={c.shipped_as}",
                                   f"props.reached={day}: closed by brain wave close ({c.done} done{to}, "
                                   f"{len(c.dropped)} dropped)"])
    return c
