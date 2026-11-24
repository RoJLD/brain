"""``brain milestone``: open items attached to no milestone: proposals, the owner's validation, new milestones (ADR
2026-11-01: always propose, never attach alone); and ``path``, the order of the milestones (brain.planpath, UX-12).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .. import config, decisions, forecast, graph, milestones, planpath, resume, status
from ._common import _kv, _now, _print_json, _project, _queue_changed, _scope, _store, _text

ORDER = 50   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 50   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain milestone suggest [--only ID]... [--write]   the open items attached to no milestone, each with its proposal
                 (props.milestone_proposed, never overwritten) or a new one: the milestone most items of its spec
                 belong to, then its depends_on neighbours', then its theme's; --write stores the new ones (ms-x?)
  brain milestone apply [--only ID]... [--skip ID]... [--set ID=MS]... [--write]   once {owner} has validated: the
                 part_of edges of the proposals (or of the values set), the proposals cleared; without --write, the
                 plan
  brain milestone add ID --title T --trigger TR [--item ID]... [--parent MS] --why W [--option "A: c"]... [--ddr D]
                 a new milestone through the decision queue: the first run asks {owner}, the same command once the
                 creation is chosen writes the Milestone and its items' part_of edges
  brain milestone path [--check] [--json] [--history] [--width N]   the order of the milestones (UX-12): an arc A -> B
                 when an item of B still waits on an item of A (both open; --history: the done pairs too), weighted by
                 its pairs, a declared depends_on between two milestones winning; the ranks left to right, the
                 milestones of a rank in parallel with their p50 (the last brain forecast's), the mutual waits as
                 knots, the longest chain of p50 work marked; --check lists each knot, its pairs each way and how to
                 settle it (exit 1 while one is left); --json the data (v 1, the Path view's and the PERT view's)
"""


def _ids(values: list[str] | None) -> list[str] | None:
    """Repeatable ids, each value possibly a comma-separated list."""
    if values is None:
        return None
    return [v.strip() for x in values for v in x.split(",") if v.strip()]


def cmd_milestone(args, root: Path) -> int:
    if args.milestone_cmd == "suggest" and args.all:
        if args.write:
            raise SystemExit("brain: milestone suggest --write takes one project")
        for p in _scope(args, root):
            for store in (s for s in p.stores if (s / "schema.yaml").is_file()) if p.root.is_dir() else ():
                print(f"== {p.name}: {store}")
                _milestone_suggest(args, p.root, store)
        return 0
    if args.milestone_cmd == "path":
        return _milestone_path(args, root)
    store = _store(args, root)
    try:
        if args.milestone_cmd == "suggest":
            return _milestone_suggest(args, root, store)
        if args.milestone_cmd == "apply":
            changes = milestones.apply(store, only=_ids(args.only), skip=_ids(args.skip), overrides=_kv(args.set),
                                       write=args.write)
            for c in changes:
                print(c.line())
            done = " written; then brain sync and brain check" if args.write else \
                f" (not written: --write once {config.name_of()} has validated)"
            print(f"apply: {len(changes)} change(s)" + (done if changes else ""))
            left = milestones.waiting(store)
            if left:
                print(f"left as proposals (milestone not created yet: brain milestone add): {', '.join(left)}")
            return 0
        return _milestone_add(args, root, store)
    except (graph.GraphError, decisions.QueueError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1


def _milestone_suggest(args, root: Path, store: Path) -> int:
    rows = milestones.suggest(store, _ids(args.only), write=args.write)
    notes_: dict[str, str] = {}
    for r in rows:
        if r.proposed and not r.exists and r.proposed not in notes_:
            notes_[r.proposed] = milestones.ddr_note(root, r.proposed)
        print(r.line(notes_.get(r.proposed, "")))
    new = sum(1 for r in rows if not r.proposed and r.suggestion)
    tail = (f" written; then brain sync and brain check, and {config.name_of()} validates (brain milestone apply)"
            if args.write else " (not written: --write)") if new else ""
    print(f"suggest: {len(rows)} open item(s) attached to no milestone, {sum(1 for r in rows if r.proposed)} "
          f"proposed already, {new} new suggestion(s){tail}")
    return 0


def _milestone_path(args, root: Path) -> int:
    """brain milestone path (brain.planpath): the project's graph, every store read as one (as the cockpit reads it),
    and its last forecast; --check exits 1 while a knot is left."""
    p = _project(args, root)
    st = resume.Store.load(Path(args.store).resolve()) if getattr(args, "store", None) else status._store(p)
    lay = planpath.layers(st, forecast.load_latest(p.name), p.name, history=args.history)
    found = planpath.problems(lay) if args.check else []
    if args.json:
        _print_json(lay)
    elif args.check:
        print("\n".join(found) if found else f"path: no mutual wait ({planpath.heading(lay)})")
    else:
        width = args.width or (shutil.get_terminal_size((planpath.WIDE, 30)).columns if sys.stdout.isatty()
                               else planpath.WIDE)
        print("\n".join([f"Milestones · Path · {p.name}: {planpath.heading(lay)}",
                         *planpath.text(lay, max(40, width))]))
    return 1 if args.check and lay["knots"] else 0


def _milestone_add(args, root: Path, store: Path) -> int:
    mid, items = args.id, _ids(args.item) or []
    ddr = decisions.find(root, args.ddr)[1] if args.ddr else milestones.milestone_ddr(root, mid)
    if ddr is None:
        known = graph.node_index(store)
        if mid in known:
            raise graph.GraphError(f"{mid}: already in the graph ({known[mid][1].get('type')}); attach items with "
                                   f"brain milestone apply --set ID={mid}")
        if not args.why:
            raise graph.GraphError(f"a new milestone is put to {config.name_of()} first: give --why (the reason to "
                                   "create it)")
        ddr, kept = milestones.ask(root, store, mid, title=args.title, trigger=_text(args.trigger), items=items,
                                   why=_text(args.why), at=args.at or _now(), parent=args.parent or "",
                                   options=args.option, context=_text(args.context),
                                   project=_project(args, root).name, session=args.session or "")
        print(f"asked {ddr['id']}; {config.name_of()} answers: brain decision answer {ddr['id']} <option>; once the "
              f"creation is chosen, run this command again")
        if kept:
            print(f"brain: warning: other proposals kept: {', '.join(kept)}")
        _queue_changed(root, args)
        return 0
    try:
        changes = milestones.create(root, store, mid, ddr, title=args.title, trigger=_text(args.trigger),
                                    items=items, parent=args.parent or "")
    except milestones.Pending as exc:
        print(f"brain: {exc}", file=sys.stderr if exc.answered else sys.stdout)
        return 1 if exc.answered else 0
    for c in changes:
        print(c.line())
    print(f"add: {mid} in the graph, {len(changes)} item(s) part of it; then brain decision ack {ddr['id']} "
          f"--applied {mid} (once answered), brain sync and brain check")
    return 0


def register(sub, ctx) -> None:
    who = ctx.who
    mi = sub.add_parser("milestone", help=f"open items attached to no milestone: proposals, {who}'s validation, new "
                                          "milestones (ADR 2026-11-01: always propose, never attach alone)").\
        add_subparsers(dest="milestone_cmd", required=True)
    ms = mi.add_parser("suggest", help="list the orphans with their proposal, or one from the signals (spec, then "
                                       "depends_on neighbours, then theme); --write stores the new ones")
    ms.add_argument("--only", action="append", help="only these items (repeatable, or comma-separated)")
    ms.add_argument("--write", action="store_true", help="store the new suggestions as props.milestone_proposed "
                                                         "and props.milestone_reason (existing proposals are kept)")
    ms.add_argument("--all", action="store_true", help="every registered project's orphans, printed (not --write)")
    mp = mi.add_parser("apply", help=f"once {who} has validated: write the part_of edges of the proposals, clear "
                                     "them (without --write: the plan)")
    mp.add_argument("--only", action="append", help="only these items (repeatable, or comma-separated)")
    mp.add_argument("--skip", action="append", help="leave these proposals (repeatable, or comma-separated)")
    mp.add_argument("--set", action="append", help=f"ID=MS: {who}'s milestone for an item instead of its proposal, "
                                                   "or for an item without one (repeatable)")
    mp.add_argument("--write", action="store_true", help="write the edges and clear the proposals")
    mpa = mi.add_parser("path", help="the order of the milestones from their items' dependencies (a declared one "
                                     "wins): ranks, parallel lanes, mutual waits as knots, the longest p50 chain")
    mpa.add_argument("--check", action="store_true", help="list the mutual waits (knots), their pairs each way and "
                                                          "how to settle them; exit 1 while one is left")
    mpa.add_argument("--json", action="store_true", help="the data: ranks, nodes, arcs, knots, chain (v 1)")
    mpa.add_argument("--history", action="store_true", help="count the done pairs too: the order the work took, not "
                                                            "only what still waits")
    mpa.add_argument("--width", type=int, help="the columns drawn (default: the terminal's; lanes from 120, a tree "
                                               "under)")
    mn = mi.add_parser("add", help=f"a new milestone through the decision queue: asks {who}, then (same command, "
                                   "once the creation is chosen) writes it and its items' part_of edges")
    mn.add_argument("id", help="the milestone id (ms-...)")
    mn.add_argument("--title", required=True)
    mn.add_argument("--trigger", required=True, help="props.trigger: when the milestone is reached (verifiable)")
    mn.add_argument("--item", action="append", help="work item that goes in it (repeatable, or comma-separated)")
    mn.add_argument("--parent", help="the milestone this one is part of")
    mn.add_argument("--why", help="the reason to create it (the recommendation of the question; first run)")
    mn.add_argument("--option", action="append", help="an alternative 'label: consequences' (up to 3; default: the "
                                                      "best existing milestone for the items, then no milestone)")
    mn.add_argument("--context", help="the question's context (default: the trigger)")
    mn.add_argument("--ddr", help="an existing DDR that asks for this milestone (default: found by its title)")
    mn.add_argument("--session", help="the asking session's id")
    mn.add_argument("--at", help="time asked (default: now)")


run = cmd_milestone
