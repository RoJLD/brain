"""``brain decision``: the owner's decision queue (records/ddr): ask, pending, answer, ack."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import answers, batch, config, decisions, defaults, notify, records
from ._common import _notify_project, _now, _on_main, _project, _queue_changed, _scope, _store, _text, _whole

ORDER = 90   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 90   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain decision ask --title T --question Q --option "A: consequences"... --why W [--multi] [--blocking] ...
                 [--low-stakes]: applied at once, provisionally, final by default 24 h later without an answer;
                 refused on money, keys, visibility, publication, accounts, arming, rules and scheduled tasks
  brain decision pending [--all] [--json]     what waits on {owner}: the queue, items' props.open, spec questions
  brain decision answer ID CHOICE... [--other TEXT]   {owner}'s choice (label, number or start of the label)
  brain decision answer --batch @FILE|-|JSON [--via ask-tool --by {owner}]   a morning session's answers in one call:
                 {"<DDR id or question>": "<label>" | ["<label>"...] | {"choices", "other", "notes"}}; exact labels
                 ("(Recommandé)" ignored, a multi_select's labels joined by ", "), {owner}'s own text only as
                 {"other": "..."}; a BOM is fine; every key is checked before any DDR is written
  brain decision answer --captured [--session ID] [--no-merge] [--retries 3] [--dry-run]   the answers this
                 session's question tool captured (each tied to the DDR brain decision batch printed), recorded in a
                 worktree, one PR, merged with its retries; in an agent's session an answer relayed by a message is
                 never recorded (apply it, then ack)
  brain decision defaulted [--all] [--apply] [--seen [ID...]] [--on-main] [--json]   the review list: the decisions
                 taken by default, the provisional ones, the reversed ones (reverse one: answer ID <option> --again);
                 --apply and --seen never write a main checkout on main unless --on-main
  brain decision batch [--project P | --all] [--size 4] [--zen [--minutes 5]] [--json]   the zen mode: the pending
                 decisions in batches for the question tool (AskUserQuestion: up to 4 questions, a header of 12
                 characters, 2 to 4 options, the recommended one first and marked "(Recommandé)"), the blocking ones
                 first and flagged, then by what they unblock; a brainstorm's numbered questions (Q1.., BRIQUE-1..)
                 together, else one item's or one spec's; --json: each batch's questions, the tool's input as is, and
                 its DDR ids; --zen: the morning digest, the batches that fit in --minutes (0: all), then the rest
  brain decision ack ID --applied WHERE...    read and applied (ADR, item, spec), then archived (--keep: not yet)
  brain decision archive [ID]... | view [--all] [--write] | announce
                 a --blocking ask is also sent through the notification channels (brain notify; --no-notify: not)
"""
NO_PROJECT = {"announce"}   # its parsers that take no --project after them


def cmd_decision(args, root: Path) -> int:
    sub = args.decision_cmd
    try:
        if sub == "pending":
            return cmd_pending(args, root)
        if sub == "batch":
            return cmd_batch(args, root)
        if sub == "view":
            if args.all:
                if args.write:
                    raise SystemExit("brain: decision view --write takes one project (brain refresh --all writes "
                                     "every project's views)")
                for p in _scope(args, root):
                    if p.shares_root_with:   # the root's queue is its owner's, printed once
                        continue
                    print(decisions.view(p.root, p.name) if p.root.is_dir() else f"# {p.name}: {p.root} not found\n",
                          end="")
                return 0
            here = _project(args, root)
            name = here.shares_root_with or here.name
            if args.write:
                _queue_changed(root, args)
            else:
                print(decisions.view(root, name), end="")
            return 0
        now = args.at or _now()
        if sub == "ask":
            ddr, out = decisions.ask(
                root, title=args.title, question=_text(args.question), options=args.option, why=_text(args.why),
                at=now, context=_text(args.context), blocks=args.blocks or "", multi=args.multi,
                blocking=args.blocking, due=args.due or "", recommend=args.recommend or "", items=args.item,
                specs=args.spec, adrs=args.adr, project=_project(args, root).name, session=args.session or "",
                slug=args.slug or "", dry_run=args.dry_run, low_stakes=args.low_stakes)
            if out is None:
                print(records._dump_yaml(ddr), end="")
                if args.blocking and not args.no_notify:
                    print("\n".join(notify.decision(_notify_project(args, root), ddr, dry_run=True)))
                return 0
            print(f"asked {ddr['id']} ({out.relative_to(root).as_posix()}); {config.name_of()} answers: "
                  f"brain decision answer {ddr['id']} <option>")
            if ddr.get("default"):
                print(f"low-stakes: apply {ddr['default']['option']!r} now, provisionally; it is final by default at "
                      f"{ddr['default']['after']} unless {config.name_of()} answers (brain decision defaulted)")
            if args.blocking and not args.no_notify:
                print("\n".join(notify.decision(_notify_project(args, root), ddr)))
        elif sub == "answer" and args.captured:
            return cmd_answer_captured(args, root)
        elif sub == "defaulted":
            return cmd_defaulted(args, root)
        elif sub == "answer" and args.batch:
            if args.id or args.choice or args.other or args.notes:
                raise decisions.QueueError("--batch takes the answers from its JSON: no ID, CHOICE, --other or "
                                           "--notes")
            done = batch.answer_batch(root, _answers(args.batch), by=args.by, via=args.via, at=now,
                                      again=args.again, check=answers.refusal)
            print(f"answered {len(done['answered'])} decision(s) via {args.via} by {args.by}:")
            print("\n".join(f"  {d['id']}: {decisions._answer_text(d)}" for d in done["answered"]))
            if done["skipped"]:
                print(f"left pending (no answer): {', '.join(done['skipped'])}")
            print("the model in charge applies each answer, then brain decision ack ID --applied <where>")
        elif sub == "answer":
            if not args.id:
                raise decisions.QueueError("answer takes a DDR id and a choice, or --batch with the answers")
            ddr = decisions.answer(root, args.id, args.choice, other=_text(args.other), notes=_text(args.notes),
                                   by=args.by, via=args.via, at=now, again=args.again, check=answers.refusal)
            print(f"answered {ddr['id']}: {decisions._answer_text(ddr)}; the model in charge applies it, then "
                  f"brain decision ack {ddr['id']} --applied <where>")
        elif sub == "ack":
            ddr, unknown = decisions.ack(root, args.id, args.applied, session=args.session or "", at=now,
                                         archive=not args.keep, store=_store(args, root))
            print(f"{ddr['status']} {ddr['id']} (applied in {', '.join(args.applied)})")
            if unknown:
                print(f"brain: warning: not in the graph yet: {', '.join(unknown)} (brain sync after the ADR?)")
        else:
            done = decisions.archive(root, args.ids, session=args.session or "", at=now)
            print(f"archived {len(done)}: {', '.join(done) or 'none'}")
    except (decisions.QueueError, batch.BatchError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    _queue_changed(root, args)
    return 0


def _answers(value: str) -> str:
    """--batch: @FILE or a file path (UTF-8 with or without a BOM, or UTF-16), '-' (stdin), else the JSON itself."""
    if value.startswith("@"):
        if not Path(value[1:]).is_file():
            raise batch.BatchError(f"{value[1:]}: no such file")
        return batch.decode(Path(value[1:]).read_bytes())
    if value != "-" and not value.lstrip("\ufeff").lstrip().startswith(("{", "[")) and Path(value).is_file():
        return batch.decode(Path(value).read_bytes())
    if value == "-":
        return batch.decode(sys.stdin.buffer.read()) if hasattr(sys.stdin, "buffer") else sys.stdin.read()
    return value


def _capture_line(c: dict) -> str:
    """A captured answer as --captured lists it, the refused ones marked (never recorded, --again included)."""
    why = answers.refused(c)
    return (f"  {c['ddr']} ({c.get('header')}): {c['answer']}" + (f" — notes: {c['notes']}" if c.get("notes") else "")
            + (f" — refused: {why}" if why else ""))


def _left_lines(out: dict) -> list[str]:
    """What --captured did not write, each kind apart (the retired ones are never recorded, --again included; only
    the ones no longer pending are --again's), then the merge's log."""
    lines = [f"retired, never recorded: {'; '.join(out['refused'])}"] if out["refused"] else []
    if out["skipped"]:
        lines.append(f"not pending, left: {', '.join(out['skipped'])} (--again replaces an answer)")
    if out["missing"]:
        lines.append(f"not on the default branch yet, left captured: {', '.join(out['missing'])} (record them once "
                     "the branch that asked them is merged)")
    return lines + [f"  {line}" for line in out["log"]]


def cmd_answer_captured(args, root: Path) -> int:
    """``brain decision answer --captured``: this session's captured answers, recorded in one PR (brain.answers)."""
    if args.id or args.choice or args.other or args.notes or args.batch:
        raise decisions.QueueError("--captured takes the answers from the capture: no ID, CHOICE, --other, --notes "
                                   "or --batch")
    session = args.session or answers.session_id()
    if answers.agent_session() and not session:
        raise decisions.QueueError("--captured in an agent's session needs its id (CLAUDE_CODE_SESSION_ID)")
    if answers.agent_session() and args.session and args.session != answers.session_id():
        raise decisions.QueueError("an agent's session records only its own captured answers (one writer per batch)")
    project = _project(args, root)
    caps = answers.unrecorded(session, project.name)
    if not caps:
        print(f"no captured answer to record for {project.name}" + (f" (session {session})" if session else ""))
        return 0
    for c in caps:
        print(_capture_line(c))
    if args.dry_run:
        print(f"dry run: {len(caps)} answer(s) to record in one PR")
        return 0
    try:
        out = answers.record_captured(project, caps, owner=args.by, session=session, merge=not args.no_merge,
                                      retries=args.retries, again=args.again)
    except answers.AnswersError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    print(f"recorded {len(out['recorded'])} answer(s) on {out['branch']}: {out['pr']}")
    for line in _left_lines(out):
        print(line)
    if not out["merged"]:
        print(f"not merged yet: {out['pr']} (worktree {out['worktree']})")
    else:   # the hooks read the main checkout's queue: the other sessions see the answers once it is pulled
        print(f"merged: once {project.root} is pulled, the hooks announce the answers to every session of the project")
    print("the sessions that own each decision apply it, then brain decision ack ID --applied <where>")
    return 0


def _own_records(projs: list) -> list:
    """The projects that hold their root's records (a DDR folder, and the root is theirs: a project that shares it
    leaves them to its owner)."""
    return [p for p in projs if (p.root / records.RECORDS_DIR / "ddr").is_dir() and not p.shares_root_with]


def cmd_defaulted(args, root: Path) -> int:
    """``brain decision defaulted``: the review list of the decisions taken by default (brain.defaults)."""
    now = args.at or _now()
    scope = _own_records(_scope(args, root))
    if args.seen is not None and answers.agent_session():
        raise decisions.QueueError(f"--seen is {config.name_of()}'s own note that they read the defaults: from their "
                                   "terminal or the cockpit, not an agent's session")
    if args.apply or args.seen is not None:
        _defaulted_writes(args, [p for p in scope if _writable(args, p)], now)
    out = [{"project": p.name, **defaults.review(p.root, now)} for p in scope]
    if args.json:
        print(json.dumps(out if args.all else (out[0] if out else {}), ensure_ascii=False, indent=1))
        return 0
    for d in out:
        print("\n".join(defaults.render(d["project"], d)))
    return 0


def _writable(args, p) -> bool:
    """--apply and --seen write a project's records and queue view: never a main checkout on main or master unless
    --on-main (brain refresh's rule; a later pull there would abort over the records changed in place)."""
    branch = "" if args.on_main else _on_main(p.root)
    if branch:
        print(f"{p.name}: main checkout on {branch}: not written (run it from a worktree, or --on-main)")
    return not branch


def _defaulted_writes(args, scope: list, now: str) -> None:
    """--apply, then --seen, in each project of ``scope``; every --seen id is found and checked in every project
    before any is marked; the queue views are rewritten even when a check refuses (the defaults taken stay)."""
    try:
        for p in scope if args.apply else []:
            for ddr_id in defaults.finalize(p.root, now):
                print(f"{p.name}: {ddr_id} taken by default")
        if args.seen is not None:
            for p, ids in _seen_plan(args, scope):
                done = defaults.seen(p.root, ids, at=now, session=args.session or "", exact=args.all)
                print(f"{p.name}: reviewed {len(done)}: {', '.join(done) or 'none'}")
    finally:
        for p in scope:
            decisions.write_view(p.root, p.name)


def _holds(root: Path, ddr_id: str) -> bool:
    try:
        decisions.find(root, ddr_id, exact=True)
    except decisions.QueueError:
        return False
    return True


def _seen_plan(args, scope: list) -> list[tuple]:
    """(project, the ids --seen names there): with no id, every project (each default not reviewed yet); with --all,
    each id in the one project that holds a DDR of that exact id (a DDR id is its project's own: the part of an id
    one project takes would name another DDR in each). Every id is found and checked before any is marked (what
--apply took before stays taken)."""
    if not args.seen or not args.all:
        plan = [(p, list(args.seen or [])) for p in scope]
    else:
        where: dict[str, tuple] = {}
        for ddr_id in args.seen:
            hits = [p for p in scope if _holds(p.root, ddr_id)]
            if len(hits) != 1:
                raise decisions.QueueError(f"{ddr_id}: " + (
                    f"in several projects ({', '.join(p.name for p in hits)}): --project P --seen ID" if hits else
                    "no project written here holds a DDR of that id (--all takes full ids; a main checkout is not "
                    "written without --on-main)") + ": nothing marked")
            where.setdefault(hits[0].name, (hits[0], []))[1].append(ddr_id)
        plan = list(where.values())
    for p, ids in plan:
        if ids:
            defaults.seen_targets(p.root, ids, exact=args.all)
    return plan


def cmd_batch(args, root: Path) -> int:
    """``brain decision batch``: the zen mode, for this project or every registered one."""
    scope = [p for p in _scope(args, root) if p.root.is_dir()]
    data = [batch.build(p, size=args.size, named=args.all) for p in scope]
    for p, d in zip(scope, data):   # the capture hook ties each answer to its DDR by these (brain.answers)
        try:
            answers.remember(p.name, p.root, d["batches"])
        except OSError as exc:
            print(f"brain: warning: the asked questions were not written to the ledger: {exc}", file=sys.stderr)
    if args.json:
        print(json.dumps(data if args.all else data[0], ensure_ascii=False, indent=1))
        return 0
    shown = [d for d in data if not args.all or d["batches"] or sum(d["rest"].values())]
    for i, d in enumerate(shown):
        print(("\n" if i else "") + "\n".join(batch.zen(d, args.minutes) if args.zen else batch.render(d)))
    if args.all:
        print(f"all: {sum(d['decisions'] for d in data)} decision(s) in {sum(len(d['batches']) for d in data)} "
              f"batch(es) across {sum(1 for d in data if d['batches'])} of {len(data)} project(s)")
    return 0


def cmd_pending(args, root: Path) -> int:
    kinds = tuple(args.kind) if args.kind else decisions.KINDS
    data = [decisions.pending(p, kinds, with_graph=not args.no_graph) for p in _scope(args, root)]
    if args.json:
        print(json.dumps(data if args.all else data[0], ensure_ascii=False, indent=1))
        return 0
    for d in data:
        print("\n".join(decisions.render_pending(d)))
    if len(data) > 1:
        print(f"all: {sum(d['waiting_on_owner'] for d in data)} waiting on {config.name_of()} in "
              f"{sum(1 for d in data if d['waiting_on_owner'])} of {len(data)} project(s), "
              f"{sum(len(d['answered']) for d in data)} answer(s) to integrate")
    return 0


def register(sub, ctx) -> None:
    who = ctx.who
    by_ = ctx.by
    de = sub.add_parser("decision", help=f"{who}'s decision queue (records/ddr): ask, pending, answer, ack").\
        add_subparsers(dest="decision_cmd", required=True)
    da = de.add_parser("ask", help=f"put a decision to {who}: 2 to 4 options, the recommended one first, its reason")
    da.add_argument("--title", required=True, help="short header (100 characters at most)")
    da.add_argument("--question", required=True)
    da.add_argument("--option", action="append", required=True,
                    help="'label: consequences' ('label:: consequences' when the label has ': '), recommended first")
    da.add_argument("--why", required=True, help="the reason of the recommendation")
    da.add_argument("--recommend", help="the recommended label (checked: it must be the first option)")
    da.add_argument("--context", help="two lines of context")
    da.add_argument("--blocks", help="what waits on the answer")
    da.add_argument("--multi", action="store_true", help="several options can be chosen")
    da.add_argument("--blocking", action="store_true")
    da.add_argument("--due", help="YYYY-MM-DD")
    da.add_argument("--item", action="append", help="WorkItem or Milestone the answer goes to (repeatable)")
    da.add_argument("--spec", action="append", help="spec node or section (repeatable)")
    da.add_argument("--adr", action="append", help="related ADR id (repeatable)")
    da.add_argument("--slug", help="id slug (default: from the title)")
    da.add_argument("--session", help="the asking session's id")
    da.add_argument("--at", help="time asked (default: now)")
    da.add_argument("--dry-run", action="store_true")
    da.add_argument("--no-notify", action="store_true", help="a --blocking question is not sent through the "
                                                             "notification channels (brain notify)")
    da.add_argument("--low-stakes", action="store_true",
                    help="applied at once, provisionally; final by default 24 h later without an answer (brain "
                         "decision defaulted); refused on money, keys, visibility, publication, accounts, arming, "
                         "rules and scheduled tasks")
    dp = de.add_parser("pending", help=f"what waits on {who}: the queue's DDRs, items' props.open, unanswered spec "
                                       f"questions, items blocked on {who}, specs still proposed")
    dp.add_argument("--all", action="store_true", help="every registered project, then the total")
    dp.add_argument("--kind", action="append", choices=list(decisions.KINDS))
    dp.add_argument("--no-graph", action="store_true", help="the DDRs only (no research_graph pending)")
    dp.add_argument("--json", action="store_true")
    dw = de.add_parser("answer", help=f"record {who}'s answer, or a batch of answers (--batch)")
    dw.add_argument("id", nargs="?", help="a DDR id, or a part of it only one DDR has")
    dw.add_argument("choice", nargs="*", help="option label, number (1-based) or start of the label; several when "
                                              "multi_select")
    dw.add_argument("--other", help=f"{who}'s own answer, free text")
    dw.add_argument("--notes")
    dw.add_argument("--by", default=by_)
    dw.add_argument("--via", default="cli", choices=["ask-tool", "cli", "spec", "chat", "tui"])
    dw.add_argument("--again", action="store_true", help="replace an earlier answer")
    dw.add_argument("--batch", metavar="@FILE|-|JSON",
                    help="a session's answers, {id or question: label, labels or {choices, other, notes}}: @FILE, a "
                         "file path, - (stdin) or the JSON itself (brain decision batch prints the questions); "
                         "exact labels, free text only as {\"other\": ...}; a BOM is fine")
    dw.add_argument("--at")
    # the answers' lane (wi-brain-answers-lane): the capture of the question tool, recorded in one PR
    dw.add_argument("--captured", action="store_true",
                    help="record the answers this session's question tool captured, in a worktree and one PR, "
                         "merged with its retries")
    dw.add_argument("--session", help="--captured: the asking session (default: this one, CLAUDE_CODE_SESSION_ID; "
                                      "in the owner's terminal, every session's)")
    dw.add_argument("--no-merge", action="store_true", help="--captured: open the PR, do not merge it")
    dw.add_argument("--retries", type=_whole, default=answers.RETRIES,
                    help=f"--captured: merge attempts after the first (default {answers.RETRIES})")
    dw.add_argument("--dry-run", action="store_true", help="--captured: list what would be recorded")
    # decisions by default (wi-brain-decision-default): the review list
    dd = de.add_parser("defaulted", help=f"the review list: the decisions taken by default, for {who} to take note")
    dd.add_argument("--all", action="store_true", help="every registered project")
    dd.add_argument("--apply", action="store_true", help="record the defaults due now (brain refresh does it too)")
    dd.add_argument("--seen", nargs="*", metavar="ID", help=f"{who} reviewed them (every one listed when no id; "
                                                            "with --all, full ids, each in the project that holds it)")
    dd.add_argument("--on-main", action="store_true", help="--apply and --seen write a main checkout on main or "
                                                           "master too (as brain refresh --on-main)")
    dd.add_argument("--session")
    dd.add_argument("--at")
    dd.add_argument("--json", action="store_true")
    db = de.add_parser("batch", help="zen mode: the pending decisions in batches for the question tool, the blocking "
                                     "ones first, then by what they unblock, grouped by brainstorm, item or spec")
    db.add_argument("--all", action="store_true", help="every registered project")
    db.add_argument("--size", type=int, default=batch.SIZE, help=f"questions per batch, 1 to {batch.SIZE} "
                                                                  f"(default {batch.SIZE})")
    db.add_argument("--zen", action="store_true", help="the morning digest: this session's batches in full, then "
                                                       "the rest in a line each")
    db.add_argument("--minutes", type=_whole, default=batch.MINUTES,
                    help=f"--zen: the session's length (default {batch.MINUTES}; 0: every batch)")
    db.add_argument("--json", action="store_true", help="each batch's questions (the question tool's input as is), "
                                                        "ids and entries")
    dk = de.add_parser("ack", help="the model in charge read and applied the answer: integrated, then archived")
    dk.add_argument("id")
    dk.add_argument("--applied", action="append", required=True,
                    help="where it went: an ADR id, an item id, a spec section (repeatable)")
    dk.add_argument("--keep", action="store_true", help="leave it integrated, not archived yet")
    dk.add_argument("--session", help="the acknowledging session's id")
    dk.add_argument("--at")
    dr = de.add_parser("archive", help="archive integrated decisions (all of them when no id is given)")
    dr.add_argument("ids", nargs="*")
    dr.add_argument("--session")
    dr.add_argument("--at")
    dv = de.add_parser("view", help="the generated board notes/decision_queue.md (printed, or --write)")
    dv.add_argument("--write", action="store_true")
    dv.add_argument("--all", action="store_true", help="every registered project's board, printed")
    dn = de.add_parser("announce", help="SessionStart hook: answers not integrated yet (hook JSON on stdin)")
    dn.add_argument("event", nargs="?", default="SessionStart")


def early(args) -> int | None:
    if args.decision_cmd == "announce":  # a hook: standard library only, never fails
        return decisions.hook_main([args.event])
    return None


run = cmd_decision
