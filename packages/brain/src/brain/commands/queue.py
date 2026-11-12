"""``brain queue``: the owner's queue: decisions, actions only they may do, permissions an agent lacked; in three bands,
ranked by what each holds up (--explain).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import config, decisions, detail, projects, queue, records, resume
from ._common import _now, _project, _queue_changed, _scope, _text

ORDER = 100   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 100   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain queue [--project P | --all] [--kind decision|action|permission]... [--days N] [--no-graph] [--no-transcripts]
              [--explain] [--json]   {owner}'s queue: decisions (DDRs, items' props.open, spec questions), actions
                         only they may do (keys, money, arming, visibility, accounts, scheduled tasks, legal reading)
                         and permissions an agent lacked (denied tool calls in the last N days of transcripts, default
                         7; expired once their session is archived or gone); ranked in three bands (now, this week,
                         when you can) by a zero-token score of what each holds up: the priority and count of the open
                         items and milestones downstream, the critical path's slip per day of waiting and the nearest
                         milestone (the last brain forecast), a stated deadline, the minutes it takes, its age;
                         --explain shows each term; then what each gate written on a node holds (props.gate)
  brain queue order ID [N] [--band now|week|later] [--clear]   {owner}'s own order: first in its band, at position N
  brain queue add --kind action|permission --title T --what W [--item ID]... [--blocking] [--due D] [--minutes N]
                 a DDR of that kind (--due: a stated deadline, it weighs above the count; --minutes: the effort)
  brain queue add --guard guard-ID [--item ID]...   a refusal of the owner, power or third-party guard as an action:
                 its title, exact command (the question; and the command when Apply runs it) and reason from the
                 guards ledger
  brain queue done ID [--note TEXT]   {owner} did the action or granted the permission (a denial or a guard refusal:
                 until refused again)
  brain queue apply ID   {owner}'s Apply: the action's exact command (queue add --command CMD [--cwd DIR], else the one
                 its text names) shown, an install.ps1 -Apply's plan run first, run on the owner's y, logged as their action in
                 $BRAIN_HOME/ledger/cockpit-<month>.jsonl, then queue done; refused in a Claude Code session's shell
  brain queue --scope REF [...]   the queue of the projects of a node's subtree in the scope tree (brain scopes: an
                 id, a path of ids, global = --all, . or ..), one group each, then their totals
"""


def cmd_queue(args, root: Path) -> int:
    """``brain queue``: the queue of the project (a worktree of a registered checkout keeps its name), or of every
    registered project with --all; ``add`` and ``done``."""
    sub = getattr(args, "queue_cmd", None)
    try:
        if sub == "add":
            ddr, out, note = queue.add(
                root, kind=args.add_kind, title=args.title or "", what=_text(args.what), at=args.at or _now(),
                context=_text(args.context), blocks=args.blocks or "", items=args.item, specs=args.spec,
                blocking=args.blocking, due=args.due or "", minutes=args.minutes, project=_project(args, root).name,
                session=args.session or "", slug=args.slug or "", command=args.command or "", cwd=args.cwd or "",
                dry_run=args.dry_run, guard=args.guard or "")
            if note:
                print(f"brain: {note}", file=sys.stderr)
            if out is None:
                print(records._dump_yaml(ddr), end="")
                return 0
            print(f"queued {ddr['id']} ({ddr['kind']}, {out.relative_to(root).as_posix()}); once done: "
                  f"brain queue done {ddr['id']}")
            _queue_changed(root, args)
            return 0
        if sub == "apply":
            return _queue_apply(args, root)
        if sub == "order":
            print(queue.order(args.id, at=args.at or _now(), position=args.position, band=args.band or "",
                              clear=args.clear, by=args.by))
            return 0
        if sub == "done":
            print(queue.done(root, args.id, at=args.at or _now(), note=_text(args.note), by=args.by))
            if not args.id.startswith(("perm-", "guard-")):
                _queue_changed(root, args)
            return 0
    except queue.QueueError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    reg = projects.load(root)
    if args.all and not reg:
        raise SystemExit(f"brain: --all needs the project registry ({projects.REGISTRY}; $BRAIN_PROJECTS or "
                         "$CLAUDE_BRAIN_DIR)")
    # --scope REF: the projects of a node's subtree (brain.scopes), placed among every one, no outside group
    names = [p.name for p in _scope(args, root)] if args.scope else []
    many = args.all or bool(names)
    only = None if many else (getattr(args, "project_obj", None) or resume.project_for(root))
    data = queue.collect(list(reg.values()), only=only, kinds=tuple(args.kind or queue.KINDS), days=args.days,
                         with_graph=not args.no_graph, transcripts=not args.no_transcripts)
    shown = data if args.all else [d for d in data if d["project"] != queue.OUTSIDE
                                   and (not names or d["project"] in names)]
    if args.json:
        print(json.dumps(shown if many else shown[0], ensure_ascii=False, indent=1))
        return 0
    outside = 0 if many else sum(len(d["entries"]) for d in data if d["project"] == queue.OUTSIDE)
    for d in shown:
        print("\n".join(queue.render(d, outside=outside, legend=not many, why=args.explain)))
    if many:
        print("\n".join(queue.LEGEND))
        total = {k: sum(d["counts"][k] for d in shown) for k in queue.KINDS}
        what = "all" if args.all else f"scope {args.scope_node}"
        print(f"{what}: {sum(total.values())} waiting on {config.name_of()} in "
              f"{sum(1 for d in shown if d['entries'])} of {len(shown)} group(s): {total['decision']} decision(s), "
              f"{total['action']} action(s), "
              f"{total['permission']} permission(s)")
    return 0


def _queue_apply(args, root: Path) -> int:
    """``brain queue apply ID``: the owner's Apply in their terminal, the cockpit's A (brain.detail): the exact
    commands, the plan of an install.ps1 -Apply, their y, then the run, logged as their action; never from a
    session's shell."""
    p = _project(args, root)
    ddr = detail._ddr(p, args.id)
    if ddr is None or ddr.get("status") != "pending":
        print(f"brain: {args.id}: no pending action of that id in {p.root / records.RECORDS_DIR / 'ddr'}",
              file=sys.stderr)
        return 1
    e = {"id": ddr["id"], "kind": decisions.kind_of(ddr), "source": "ddr", "project": p.name,
         "title": ddr.get("title", "")}
    acts = [a for a in detail.queue_actions(e, p, ddr, via="brain queue apply") if a.kind == "apply"]
    if not acts:
        print(f"brain: {ddr['id']} names no command to apply (brain queue add --command, or the command in "
              f"backquotes in its text); do it, then brain queue done {ddr['id']}", file=sys.stderr)
        return 1
    why = detail.refused()
    if why:
        print(f"brain: {why}", file=sys.stderr)
        return 1
    a = acts[0]
    print(f"Apply {a.ref}: {ddr.get('title', '')}\nin {a.cwd}:")
    print("\n".join(f"  $ {detail.shown(s)}" for s in a.steps))
    if a.preview:
        (plan,) = detail.run(detail.Action("plan", "Plan", a.project, a.ref, a.cwd), [a.preview])
        print(f"\nThe plan ({plan['command']}, exit {plan['exit']}):\n{plan['output'] or '(no output)'}\n")
    try:
        yes = input(f"Run as {config.name_of()}, logged as your action? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:  # no terminal to answer: nothing runs
        yes = False
    if not yes:
        print("nothing run")
        return 1
    results = detail.run(a, a.steps)
    for r in results:
        print(f"{'ok' if r['exit'] == 0 else 'failed, exit ' + str(r['exit'])} in {r['seconds']} s: {r['command']}")
        if r["output"]:
            print(r["output"])
    return 0 if len(results) == len(a.steps) and all(r["exit"] == 0 for r in results) else 1


def register(sub, ctx) -> None:
    who = ctx.who
    by_ = ctx.by
    qu = sub.add_parser("queue", help=f"{who}'s queue: decisions, actions only they may do, permissions an agent "
                                      "lacked; in three bands, ranked by what each holds up (--explain)")
    qu.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    qu.add_argument("--all", action="store_true", help="every registered project, then the denials outside them")
    qu.add_argument("--scope", help="the projects of a node's subtree in the scope tree (brain scopes): an id, a "
                                    "path of ids, global (= --all), . or ..")
    qu.add_argument("--kind", action="append", choices=list(queue.KINDS))
    qu.add_argument("--days", type=int, default=queue.DAYS,
                    help=f"how far back the denied tool calls are read (default {queue.DAYS})")
    qu.add_argument("--no-graph", action="store_true", help="no research_graph pending: no spec questions")
    qu.add_argument("--no-transcripts", action="store_true", help="no transcript scan: no denied tool calls")
    qu.add_argument("--json", action="store_true", help="the data the TUI's panel reads, each entry with its how, "
                                                        "band, score terms and the items it unblocks")
    qu.add_argument("--explain", action="store_true", help="each entry's score, term by term, and why its band")
    qs = qu.add_subparsers(dest="queue_cmd")
    qa = qs.add_parser("add", help=f"put an action or a permission to {who}: a DDR of that kind (a permission in a "
                                   f"category only {who} may do is written as an action)")
    qa.add_argument("--kind", dest="add_kind", choices=["action", "permission"], default="action")
    qa.add_argument("--title", help="short header (100 characters at most; required without --guard)")
    qa.add_argument("--what", help=f"what {who} does or grants: the exact command when there is one (required "
                                   "without --guard)")
    qa.add_argument("--guard", help="a refusal of the owner, power or third-party guard (guard-...): its title, "
                                    "exact command (the question; and --command when Apply runs it) and reason come from the "
                                    "guards ledger, as an action")
    qa.add_argument("--context", help="two lines of context")
    qa.add_argument("--blocks", help="what waits on it")
    qa.add_argument("--item", action="append", help="WorkItem or Milestone it unblocks (repeatable)")
    qa.add_argument("--spec", action="append", help="spec node (repeatable)")
    qa.add_argument("--blocking", action="store_true")
    qa.add_argument("--due", help="YYYY-MM-DD: a stated deadline (it weighs above the count of what it unblocks)")
    qa.add_argument("--minutes", type=int, help=f"{who}'s effort in minutes (default 5 for an action, 1 for a "
                                                "permission)")
    qa.add_argument("--slug", help="id slug (default: from the title)")
    qa.add_argument("--session", help="the asking session's id")
    qa.add_argument("--command", help=f"an action's exact command, brain ... or install.ps1 ...: what {who}'s Apply "
                                      "shows and runs (brain queue apply ID, the cockpit's A)")
    qa.add_argument("--cwd", help="the folder --command runs in (default: the project's root)")
    qa.add_argument("--at", help="time asked (default: now)")
    qa.add_argument("--dry-run", action="store_true")
    qp = qs.add_parser("apply", help=f"{who}'s Apply: an action's exact command (its --command, else the one its text "
                                     f"names) shown, an install.ps1 -Apply's plan run first, then run once {who} "
                                     "answers y, logged as their action, then the action marked done; never from a "
                                     "Claude Code session's shell")
    qp.add_argument("id", help="a pending action DDR's id (or a part only it has)")
    qo = qs.add_parser("order", help=f"{who}'s own order: the entry first in its band, at position N (and --band to "
                                     "move it); it wins over the score; --clear gives it back to the score")
    qo.add_argument("id", help="an entry's id, as brain queue shows it")
    qo.add_argument("position", nargs="?", type=int, help="1 first")
    qo.add_argument("--band", choices=list(queue.BANDS))
    qo.add_argument("--clear", action="store_true")
    qo.add_argument("--by", default=by_)
    qo.add_argument("--at")
    qd = qs.add_parser("done", help=f"{who} did the action or granted the permission: a DDR is answered (the model "
                                    "then checks and acks it), a denial stamped in the ledger until denied again")
    qd.add_argument("id", help="a DDR id (or a part only one has), a denial's perm-... id or a guard refusal's "
                               "guard-... id")
    qd.add_argument("--note", help="what was done: granted by an allow rule, done once, ...")
    qd.add_argument("--by", default=by_)
    qd.add_argument("--at")


run = cmd_queue
