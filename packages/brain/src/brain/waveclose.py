"""``brain wave close`` (wi-brain-waves-as-releases, wi-brain-wave-ids-decoupled): the closure a version PR makes. The
wave of a release (or the current wave, when the release jumped to the next minor or major) is reached with
``props.shipped_as``; each of its open items is carried by name to a later wave (``props.carried_to``) or dropped. A
``--carry-to`` is read against the plan once the wave is closed (:func:`brain.waves._after`), so after a jump the
later waves' computed releases are the ones it names; a release with no wave yet creates the next ``wave-sN``, last,
its release pinned only when it is not the computed one. Moved out of brain.waves, which keeps the plan and its checks.

Which wave a version PR ships, which the closure rule reads (brain.waves.closure_problems): :func:`closing` says it,
:func:`as_tagged` reads a wave reached without ``props.shipped_as`` through the last release tag, and
:func:`unrecorded_ship` says when such a wave leaves it untold (wi-brain-release-check-shipped-wave).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import graph
from .waves import OPEN, Plan, WaveError, _after, _props, add, ambiguous, load, next_release, release_key


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


# --- which wave a version PR ships (wi-brain-release-check-shipped-wave) ---
# The closure rule (brain.waves.closure_problems, run by brain wave check and release_check.py --store) reads
# the wave a version names, or the current wave when the release jumps. A wave reached by brain wave close records
# what it shipped as (props.shipped_as); one reached by hand, or by an engine up to 0.5.0, does not: wave 0.3.3
# closed by hand and shipped as 0.4.0 left the version PR of 0.4.0 finding no wave of that number, or jumping onto
# the next wave, and the rule passed unread. closing says the wave, as_tagged reads such a wave through the last
# release tag, unrecorded_ship says when it leaves the answer untold.

TOLD = "_shipped_as_told"   # an in-memory key of a node as_tagged read: why it shipped as it did (never written)


def closing(plan: Plan, version: str) -> str:
    """Which wave a version PR of ``version`` closes, as said: ``wave-s3 (1.0.2, closed as 1.1.0, a jump)`` when its
    label is another release (the release jumped, or a reached wave shipped as ``version``: its props.shipped_as, or
    the last tag, :func:`as_tagged`), ``wave-s3 (1.1.0)`` when it is labelled so (or ``version`` is its id); '' when
    ``version`` names none."""
    w = plan.for_release(version)
    if w is None:
        return ""
    label = plan.label(w)
    if label == version or release_key(version) is None:
        return f"{w} ({label})"
    how = "a jump" if plan.status(w) == "pending" else (plan.nodes[w].get(TOLD) or "its props.shipped_as")
    return f"{w} ({label}, closed as {version}, {how})"


def as_tagged(plan: Plan, version: str, tag: str) -> Plan:
    """The plan as the last release tag ``tag`` (vX.Y.Z or X.Y.Z) tells it, for a version PR of ``version``
    (:func:`_told`). In memory only, nothing is written; ``plan`` itself when ``tag`` or ``version`` is no release, or
    the tag tells nothing."""
    t, v = release_key(str(tag or "").strip().removeprefix("v")), release_key(version)
    told = _told(plan, t, version) if t and v and v > t else {}
    if not told:
        return plan
    nodes = dict(plan.nodes)
    for w, (rel, why) in told.items():
        nodes[w] = {**nodes[w], "props": {**_props(nodes[w]), "shipped_as": rel}, TOLD: why}
    return Plan(nodes, parents=plan.parents, members=plan.members, deps=plan.deps, ddrs=plan.ddrs, edges=plan.edges)


def _told(plan: Plan, t: tuple[int, int, int], version: str) -> dict[str, tuple[str, str]]:
    """{wave: (what it shipped as, why)} for the waves reached without a well-formed props.shipped_as: the one
    labelled the tag's release ``t`` shipped as itself; the one reached after it (labelled above it, up to
    ``version``; alone so) ships as ``version``, closed by hand before its version PR."""
    v = release_key(version)
    bare = [w for w in plan.live if plan.status(w) == "reached" and plan.release(w)
            and not release_key(_props(plan.nodes[w]).get("shipped_as"))]
    tagged = ".".join(map(str, t))
    told = {w: (tagged, f"the last tag v{tagged}") for w in bare if plan.release(w) == t}
    after = [w for w in bare if t < plan.release(w) <= v]
    if len(after) == 1:
        told[after[0]] = (version, f"reached after the last tag v{tagged}")
    return told


def previous_wave(plan: Plan, version: str) -> str | None:
    """The last live reached wave whose release (what it shipped as, else its label) is below ``version``: the one a
    version PR of a release no wave names follows; None without one."""
    key = release_key(version)
    if key is None:
        return None
    below = [(release_key(plan.shipped(w)), w) for w in plan.live if plan.status(w) == "reached"]
    below = [(k, w) for k, w in below if k and k < key]
    return max(below)[1] if below else None


def _could_ship(plan: Plan, x: str, key: tuple[int, int, int]) -> bool:
    """Whether the wave ``x`` could have shipped as ``key``: the next minor or major after the release it counts from
    (a jump of it), above its own label. The first wave counts from nothing: it ships as its label only."""
    base, own = plan._counts[1].get(x), plan.release(x)
    return bool(base and own and key > own and key in ((base[0], base[1] + 1, 0), (base[0] + 1, 0, 0)))


def unrecorded_ship(plan: Plan, version: str, w: str | None) -> str:
    """What leaves untold the wave a version PR of ``version`` closes (``w``, :meth:`Plan.for_release`): the wave
    before it (the last reached below ``version`` when it names none; the one the jump counts from when ``w`` is the
    current wave closed as a jump) was reached without a well-formed props.shipped_as and could have shipped as
    ``version`` itself (:func:`_could_ship`). Then it may be that wave the version PR closes, not ``w`` or none, and
    the closure rule would read the wrong one or pass unread. '' when that wave records what it shipped as
    (:func:`as_tagged` reads it from the last tag), or could not have."""
    key = release_key(version)
    if key is None or (w is not None and (plan.status(w) != "pending" or plan.label(w) == version)):
        return ""
    if w is None:
        x = previous_wave(plan, version)
    else:
        i = plan.live.index(w)
        x = plan.live[i - 1] if i and plan.status(plan.live[i - 1]) == "reached" else None
    raw = _props(plan.nodes[x]).get("shipped_as") if x else None
    if x is None or release_key(raw) or not _could_ship(plan, x, key):
        return ""
    label, got = plan.label(x), "" if raw in (None, "") else f" (got {raw!r})"
    then = "names no wave" if w is None else f"would close {w} ({plan.label(w)}) as a jump"
    return (f"release {version} {then}, but {x} ({label}) before it was reached without a well-formed "
            f"props.shipped_as{got} (by hand, or by an engine up to 0.5.0) and may be the wave {version} ships: "
            f"record it, brain item set {x} props.shipped_as={version} (or ={label} if it shipped as {label}), then "
            f"brain sync")
