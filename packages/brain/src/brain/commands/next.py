"""``brain next``: what comes next, from the graph's waves at zero token (brain.waves): the current wave, its
quick wins, its carried items first, then its startable items, each group ranked (brain.ranking), what waits on the
owner, the first round of its lots (brain.lots, brain wave plan), then the next wave.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import lots, nextrelease, waves
from ._common import _project, _repos, _store

ORDER = 56   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 56   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain next [--explain] [--json]   the current wave (the lowest release not closed): its quick wins (size S, high
                 value) first, its quick-win slot (a fifth of its places: what fills it, the candidates outside the
                 wave while a place is free), its items carried from an earlier wave, then those that can start, what waits on {owner}
                 (props.open, external_blocker, pending DDRs), the other open ones, the first round of its lots (brain
                 wave plan), then the next wave; zero token, from the graph (its view: plan_graph.md). Each group is
                 ranked by {owner}'s priority (confirmed before proposed), then {owner}'s order (props.order), then
                 value over effort (WSJF: the value derived from the features delivered, a milestone moved and the
                 items unblocked, or props.value high|medium|low with props.value_reason; the effort from
                 props.size); --explain: each score's parts and the values {owner} set (brain.ranking); the
                 release forecast: whether the current wave ships as the patch it is named for or as a minor, the
                 first PR that tipped it and why (release_check --preview of the engine checkout's origin/main,
                 brain.nextrelease; advisory); the items merged but not closed (brain wave close-merged's mapping,
                 git only) count done, said in one line, those still holding work kept open; the lots without the
                 hot files by history (brain wave plan reads them)
"""


def _merged(pl: waves.Plan, repos: list) -> tuple[dict, dict]:
    """The current wave's items merged but not closed (brain.lots.merged_of): counted done in brain next too."""
    pend = waves.pending_waves(pl)
    if not pend or not repos:
        return {}, {}
    return lots.merged_of(pl, pend[0], repos)   # a repo git cannot read is skipped there, its items open


def _lots(args, root: Path, store: Path, rep: dict, merged: tuple[dict, dict]):
    """The current wave's plan (brain.lots, with the merged items already read), None without a current wave or when it
    cannot be cut. No repo is passed: the hot files by history (brain.lots.history_hot, one ``git log --numstat`` a
    repo, tens of seconds on a planning repo) are brain wave plan's, not this summary's."""
    if rep["current"] is None:
        return None
    try:
        name = _project(args, root).name
    except SystemExit:
        name = ""
    try:
        return lots.plan(store, root, rep["current"]["id"], name, merged=merged)
    except Exception:   # noqa: BLE001 - the lots are a summary: brain next prints the waves whatever they say
        return None


def cmd_next(args, root: Path) -> int:
    store = _store(args, root)
    repos = [(r.name, r.path) for r in _repos(args, root)]
    pl = waves.load(store, root)
    merged = _merged(pl, repos)
    rep = waves.next_report(lots.as_done(pl, merged[1]))
    wp = _lots(args, root, store, rep, merged)
    fc = nextrelease.forecast([path for _, path in repos]) if rep["current"] is not None else None
    if args.json:
        print(json.dumps(rep | {"lots": wp.as_dict() if wp else None, "forecast": fc, "merged": merged[0] or None},
                         indent=2, ensure_ascii=False))
    else:
        out = waves.render_next(rep, explain=args.explain)
        if rep["current"] is not None:   # under the current wave's head
            out[1:1] = [f"  {line}" for line in nextrelease.lines(fc, rep["current"]["release"])
                        + _merged_line(merged[0])]
        at = next((k for k, line in enumerate(out) if line.startswith("Next:")), len(out))
        print("\n".join(out[:at] + (lots.summary(wp) if wp else []) + out[at:]))   # the current wave's, before the next
    return 0


def _merged_line(m: dict) -> list[str]:
    items, kept = (m or {}).get("items") or {}, (m or {}).get("kept") or {}
    out = [f"merged, to close ({len(items)}), counted done: {', '.join(items)} "
           f"({lots.close_advice(m['release'], kept)})"] if items else []
    if kept:
        out.append(f"merged, work left, kept open ({len(kept)}): {', '.join(kept)}")
    return out


def register(sub, ctx) -> None:
    nx = sub.add_parser("next", help=f"the current wave: carried items first, then startable ones, what waits on "
                                     f"{ctx.who}, then the next wave (zero token)")
    nx.add_argument("--json", action="store_true", help="the data, as JSON")
    nx.add_argument("--explain", action="store_true", help="each carried and startable item's score: value (its "
                                                           "parts, or the owner's props.value) over effort (its size)")


run = cmd_next
