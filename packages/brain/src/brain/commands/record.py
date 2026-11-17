"""``brain record``: write and validate DDR, SR and AR records."""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import actions, answers, backfill, decisions, graph, paths, provenance, records, transcript
from ._common import _now, _store

ORDER = 10   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 10   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain record sr   [--session ID | --transcript PATH] [--summary TEXT] [--item ID]... [--closed] [--replace]
  brain record ar   --import [--session ID] [--since DATE] | --from-transcript PATH | --session ID --kind K ...
  brain record ddr  --file DDR.yaml | --title T --question Q --option "label: consequences"... --why W ...
                    | --id ID [--answer LABEL]... [--other TEXT] [--read] [--applied WHERE]... | --import
                    (an answer, by --id or in a --file: in an agent's session only one its question tool captured)
  brain record backfill [--since DATE] [--until DATE] [--quiet-hours N] [--update] [--no-subagents] [--no-ledger]
                    [--dry-run]   the SRs and ARs of every transcript on this machine (pushes, PRs, the commits
                    the repos' history confirms, the ledger's live captures); a rerun writes nothing new
  brain record check | sync
"""


def _transcript_for(args) -> Path:
    if getattr(args, "transcript", None):
        return Path(args.transcript)
    if not getattr(args, "session", None):
        raise SystemExit("brain: give --session ID or --transcript PATH")
    t = paths.find_transcript(args.session)
    if not t:
        raise SystemExit(f"brain: no transcript for session {args.session} under {paths.projects_dir()}")
    return t


def cmd_record_sr(args, root: Path) -> int:
    path = _transcript_for(args)
    main_stats, subs, n_subs = transcript.session_stats(path)
    sid = main_stats.session_id or path.stem
    ar_ids = [r["id"] for r in records.ledger_records("ar", sid)]
    ar_ids += [a["id"] for _, a in records.load(root)["ar"] if a["session"]["id"] == sid]
    ddr_ids = [r["id"] for r in records.ledger_records("ddr", sid)]
    items = list(args.item or [])
    for r in records.ledger_records("ar", sid):
        items += [i for i in r.get("items", []) if i not in items]
    model = main_stats.models.most_common(1)[0][0] if main_stats.models else ""
    prov = provenance.for_session(model, main_stats.first_ts[:10], root, session_id=sid)
    sr = main_stats.record(path, status="closed" if args.closed else "open", summary=args.summary or "",
                           extra_items=items, actions=ar_ids, ddrs=ddr_ids, subagents=subs, subagent_count=n_subs,
                           provenance=prov)
    if args.dry_run:
        print(records._dump_yaml(records.validate("sr", sr)))
        return 0
    out = records.write(root, "sr", sr, replace=args.replace)
    print(f"wrote {out.relative_to(root).as_posix()}")
    return 0


def cmd_record_ar(args, root: Path) -> int:
    if args.import_:
        counts = records.import_ledger(root, ("ar",), args.session or "", args.since or "")
        print(f"imported {counts['ar']} AR(s) from {paths.ledger_dir()}")
        return 0
    if args.from_transcript or (args.session and not args.kind):
        path = _transcript_for(argparse.Namespace(transcript=args.from_transcript, session=args.session))
        found = actions.from_transcript(path)
        n = 0
        for ar in found:
            if args.dry_run:
                print(ar)
            elif records.write(root, "ar", ar) is not None:
                n += 1
        print(f"{len(found)} AR(s) found in {path.name}, {n} written")
        return 0
    if not args.kind:
        raise SystemExit("brain: give --import, --from-transcript PATH, or --kind with its fields")
    at = args.at or _now()
    meta = {"session_id": args.session or "unknown", "tool": args.tool, "model": args.model, "effort": args.effort,
            "version": args.version}
    fields = {"repo": args.repo, "branch": args.branch, "sha": args.sha, "subject": args.subject,
              "items": args.item or []}
    if args.kind == "pr":
        fields["pr"] = {k: v for k, v in {"number": args.pr, "url": args.url, "action": args.action}.items() if v}
    if args.kind == "adr":
        fields["adr"] = {"id": args.adr}
    if args.kind == "ddr":
        fields["ddr"] = args.ddr
    if args.kind == "tag":
        fields["tag"] = args.tag
    key = args.key or args.sha or args.adr or args.ddr or (f"{args.repo}-{args.pr}" if args.pr else at[11:19])
    ar = actions.make_ar(args.kind, f"{actions.slug(str(key), 48)}", at, meta, "cli", **fields)
    if args.dry_run:
        print(records.validate("ar", ar))
        return 0
    out = records.write(root, "ar", ar)
    print(f"wrote {ar['id']} to {out.relative_to(root).as_posix()}" if out else f"{ar['id']} already recorded")
    return 0


def cmd_record_backfill(args, root: Path) -> int:
    report = backfill.run(root, since=args.since or "", until=args.until or "", quiet_hours=args.quiet_hours,
                          subagents=not args.no_subagents, ledger=not args.no_ledger, update=args.update,
                          dry_run=args.dry_run)
    print(backfill.format_report(report, args.dry_run))
    return 0


_parse_option = decisions.parse_option


def _one_writer(ddr: dict, before: dict | None) -> None:
    """The answers' one-writer rule (brain.answers.refusal) on an answer this command writes: in an agent's session,
    only one this session's question tool captured; an answer the record already held passes as it is."""
    ans = ddr.get("answer") if isinstance(ddr, dict) and isinstance(ddr.get("answer"), dict) else None
    if not ans or ans == (before or {}).get("answer"):
        return   # no answer written (a record that is no mapping fails its schema later)
    why = answers.refusal(str(ddr.get("id") or ""), list(ans.get("choices") or []), str(ans.get("other") or ""))
    if why:
        raise SystemExit(f"brain: {why}")


def _existing(root: Path, ddr) -> dict | None:
    """The record a DDR read from --file replaces, None when there is none."""
    ddr_id = ddr.get("id") if isinstance(ddr, dict) else None
    f = root / records.RECORDS_DIR / "ddr" / f"{ddr_id}.yaml"
    return graph._yaml().safe_load(f.read_text(encoding="utf-8")) if ddr_id and f.is_file() else None


def cmd_record_ddr(args, root: Path) -> int:
    yaml = graph._yaml()
    if args.import_:
        counts = records.import_ledger(root, ("ddr",), args.session or "", args.since or "")
        print(f"imported {counts['ddr']} DDR(s) from {paths.ledger_dir()}")
        return 0
    now = args.at or _now()
    if args.id:  # stamp an existing DDR: answer, read, applied, archived
        f = root / records.RECORDS_DIR / "ddr" / f"{args.id}.yaml"
        if not f.exists():
            raise SystemExit(f"brain: no {f.relative_to(root).as_posix()}")
        ddr = yaml.safe_load(f.read_text(encoding="utf-8"))
        if args.answer or args.other:
            ddr["answer"] = {"at": now, "by": args.by, "via": args.via}
            if args.answer:
                ddr["answer"]["choices"] = args.answer
            if args.other:
                ddr["answer"]["other"] = args.other
            ddr["status"] = "answered"
            _one_writer(ddr, None)
        if args.read:
            ddr["read"] = {"at": now, "session": args.session or "unknown"}
        if args.applied:
            ddr["applied"] = {"at": now, "session": args.session or "unknown", "in": args.applied}
            ddr.setdefault("read", {"at": now, "session": args.session or "unknown"})
            ddr["status"] = "integrated"
        if args.archive:
            ddr["archived"] = {"at": now, "session": args.session or "unknown"}
            ddr["status"] = "archived"
        out = records.write(root, "ddr", ddr, replace=True)
        print(f"updated {out.relative_to(root).as_posix()} ({ddr['status']})")
        return 0
    if args.file:
        ddr = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))
    else:
        if not (args.title and args.question and args.option):
            raise SystemExit("brain: a new DDR needs --title, --question and 2 to 4 --option (recommended first)")
        options = [_parse_option(o) for o in args.option]
        ddr = {"v": 1, "id": f"ddr-{now[:10]}-{actions.slug(args.slug or args.title, 48)}", "title": args.title,
               "question": args.question}
        if args.context:
            ddr["context"] = args.context
        if args.blocks:
            ddr["blocks"] = args.blocks
        ddr.update({"options": options, "recommendation": {"option": options[0]["label"], "why": args.why or ""},
                    "multi_select": args.multi, "other_allowed": True, "blocking": args.blocking,
                    "status": "pending", "asked": {"at": now, "by": args.session or "unknown", "via": "cli"}})
        links = {k: v for k, v in {"adrs": args.adr, "items": args.about_item, "specs": args.spec}.items() if v}
        if links:
            ddr["links"] = links
    _one_writer(ddr, _existing(root, ddr))
    if args.dry_run:
        print(records._dump_yaml(records.validate("ddr", ddr)))
        return 0
    out = records.write(root, "ddr", ddr, replace=args.replace)
    print(f"wrote {out.relative_to(root).as_posix()}")
    return 0


def cmd_record_check(args, root: Path) -> int:
    errors, warnings = records.check(root)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    counts = {k: len(v) for k, v in records.load(root).items()}
    print(f"records: {counts['ddr']} DDR, {counts['sr']} SR, {counts['ar']} AR; "
          f"{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


def cmd_record_sync(args, root: Path) -> int:
    n, e, left = records.write_graph(root, _store(args, root))
    print(f"records graph: {n} node(s), {e} edge(s)" + (f", {left} link(s) to nodes not in the store" if left else ""))
    return 0


def register(sub, ctx) -> None:
    by_ = ctx.by
    rec = sub.add_parser("record", help="write and validate DDR, SR and AR records").add_subparsers(
        dest="record_kind", required=True)
    sr = rec.add_parser("sr", help="session record from a transcript")
    sr.add_argument("--session")
    sr.add_argument("--transcript")
    sr.add_argument("--summary", help="short summary (default: the session title)")
    sr.add_argument("--item", action="append", help="item touched (repeatable)")
    sr.add_argument("--closed", action="store_true", help="the session is over")
    sr.add_argument("--replace", action="store_true")
    sr.add_argument("--dry-run", action="store_true")

    ar = rec.add_parser("ar", help="action records: import the ledger, recover from a transcript, or one by hand")
    ar.add_argument("--import", dest="import_", action="store_true", help="import the local ledger's ARs")
    ar.add_argument("--from-transcript", help="recover pushes and PRs from a transcript")
    ar.add_argument("--session", help="session id (filter for --import; a transcript to read; the actor)")
    ar.add_argument("--since", help="ISO date or time: import only from then")
    ar.add_argument("--kind", choices=["commit", "push", "pr", "tag", "adr", "ddr"])
    for f in ("repo", "branch", "sha", "subject", "url", "adr", "ddr", "tag", "model", "effort", "version", "at",
              "key"):
        ar.add_argument(f"--{f}")
    ar.add_argument("--pr", type=int)
    ar.add_argument("--action", choices=["created", "merged", "linked", "closed"])
    ar.add_argument("--tool", default="claude-code")
    ar.add_argument("--item", action="append")
    ar.add_argument("--dry-run", action="store_true")

    dd = rec.add_parser("ddr", help="decision discussion record: new, from a file, stamped, or imported")
    dd.add_argument("--import", dest="import_", action="store_true", help="import the question tool's captures")
    dd.add_argument("--file", help="a DDR in YAML to validate and write")
    dd.add_argument("--id", help="an existing DDR to answer or stamp")
    dd.add_argument("--title")
    dd.add_argument("--slug", help="id slug (default: from the title)")
    dd.add_argument("--question")
    dd.add_argument("--context")
    dd.add_argument("--blocks")
    dd.add_argument("--option", action="append", help="'label: consequences', the recommended one first (2 to 4)")
    dd.add_argument("--why", help="reason of the recommendation")
    dd.add_argument("--multi", action="store_true", help="several options can be chosen")
    dd.add_argument("--blocking", action="store_true")
    dd.add_argument("--adr", action="append", help="ADR id the answer went to (repeatable)")
    dd.add_argument("--about-item", action="append", help="WorkItem or Milestone id (repeatable)")
    dd.add_argument("--spec", action="append", help="spec node id or section (repeatable)")
    dd.add_argument("--answer", action="append", help="chosen option label (repeatable); in an agent's session only "
                                                      "an answer its own question tool captured, never one relayed "
                                                      "by a message (as brain decision answer)")
    dd.add_argument("--other", help="free-text answer (the same rule)")
    dd.add_argument("--by", default=by_)
    dd.add_argument("--via", default="chat", choices=["ask-tool", "cli", "spec", "chat", "tui"])
    dd.add_argument("--read", action="store_true", help="stamp: the model in charge read the answer")
    dd.add_argument("--applied", action="append", help="stamp: applied in this ADR, item or spec (repeatable)")
    dd.add_argument("--archive", action="store_true")
    dd.add_argument("--session", help="session id of the asker or of the stamp")
    dd.add_argument("--since")
    dd.add_argument("--at", help="time of the question or stamp (default: now)")
    dd.add_argument("--replace", action="store_true")
    dd.add_argument("--dry-run", action="store_true")

    bf = rec.add_parser("backfill", help="SRs and ARs from every transcript on this machine (idempotent)")
    bf.add_argument("--since", help="sessions started from this ISO date or time")
    bf.add_argument("--until", help="sessions started before this ISO date or time (a month: --since 2026-10-01 "
                                    "--until 2026-11-01)")
    bf.add_argument("--quiet-hours", type=float, default=backfill.QUIET_HOURS,
                    help=f"a session is over once its transcript is this old; a younger one gets its ARs, its SR "
                         f"on a later run (default {backfill.QUIET_HOURS})")
    bf.add_argument("--update", action="store_true",
                    help="rewrite an SR whose transcript grew since (its hand-written summary and ids are kept)")
    bf.add_argument("--no-subagents", action="store_true", help="skip the subagents' transcripts")
    bf.add_argument("--no-ledger", action="store_true", help="skip the local ledger's ARs (the hooks' capture)")
    bf.add_argument("--dry-run", action="store_true", help="count what would be written; write nothing")
    rec.add_parser("check", help="validate every record and scan them for secrets")
    rec.add_parser("sync", help="write the records' graph view (nodes/_generated_records.yaml)")


def run(args, root: Path) -> int:
    return {"sr": cmd_record_sr, "ar": cmd_record_ar, "ddr": cmd_record_ddr, "backfill": cmd_record_backfill,
            "check": cmd_record_check, "sync": cmd_record_sync}[args.record_kind](args, root)
